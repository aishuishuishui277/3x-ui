import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sqlite3
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
M = module('maintainer', ROOT / 'server/xui-maintain.py')
P = module('sponsor_patch', ROOT / 'maintenance/patch.py')
T = module('track', ROOT / 'maintenance/track.py')

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def database(self, name='db'):
        p = self.d / name
        c = sqlite3.connect(p)
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE t (n INTEGER)'); c.execute('INSERT INTO t VALUES (42)'); c.commit()
        return p, c
    def test_backup_includes_live_wal(self):
        p, c = self.database()
        try:
            self.assertTrue(Path(str(p) + '-wal').exists())
            target = self.d / 'backup'
            M.backup_sqlite(p, target)
            with contextlib.closing(sqlite3.connect(target)) as db: self.assertEqual(db.execute('SELECT n FROM t').fetchall(), [(42,)])
        finally: c.close()
    def package(self, extra=None):
        tag = 'v3.10.2-ns1'
        elf = b'\x7fELF\x02\x01' + b'\0' * 12 + b'\x3e\x00' + b'x' * 50
        manifest = dict(schema=1, architecture='linux-amd64', release_tag=tag, tag='v3.10.2',
                        panel_sha256=hashlib.sha256(elf).hexdigest(), xray_sha256=hashlib.sha256(elf).hexdigest())
        files = {'x-ui/x-ui': elf, 'x-ui/bin/xray-linux-amd64': elf,
                 'x-ui/manifest.json': json.dumps(manifest).encode(), 'x-ui/LICENSE': b'GPL'}
        with tarfile.open(self.d / M.ASSET, 'w:gz') as tar:
            for name in ('x-ui', 'x-ui/bin'):
                info = tarfile.TarInfo(name); info.type = tarfile.DIRTYPE; tar.addfile(info)
            for name, data in files.items():
                info = tarfile.TarInfo(name); info.size = len(data); tar.addfile(info, io.BytesIO(data))
            if extra: tar.addfile(extra)
        (self.d / 'manifest.json').write_text(json.dumps(manifest))
        self.sums()
        return tag
    def sums(self):
        (self.d / 'SHA256SUMS').write_text(''.join(M.sha(self.d / n) + '  ' + n + '\n' for n in (M.ASSET, 'manifest.json')))
    def test_valid_amd64_package(self):
        tag = self.package(); self.assertEqual(M.validate_package(self.d, tag)['tag'], 'v3.10.2')
    def test_corrupted_download_rejected(self):
        tag = self.package()
        with open(self.d / M.ASSET, 'ab') as f: f.write(b'tampered')
        with self.assertRaisesRegex(ValueError, 'SHA256'): M.validate_package(self.d, tag)
    def test_traversal_rejected(self):
        tag = self.package(tarfile.TarInfo('../evil'))
        with self.assertRaisesRegex(ValueError, 'unsafe'): M.validate_package(self.d, tag)
    def test_symlink_rejected(self):
        entry = tarfile.TarInfo('x-ui/LICENSE'); entry.type = tarfile.SYMTYPE; entry.linkname = '/etc/shadow'
        tag = self.package(entry)
        with self.assertRaisesRegex(ValueError, 'unsafe'): M.validate_package(self.d, tag)
    def test_wrong_arch_manifest_rejected(self):
        tag = self.package()
        obj = json.loads((self.d / 'manifest.json').read_text()); obj['architecture'] = 'linux-arm64'
        (self.d / 'manifest.json').write_text(json.dumps(obj)); self.sums()
        with self.assertRaisesRegex(ValueError, 'target mismatch'): M.validate_package(self.d, tag)
    def test_unapproved_archive_never_stops_service(self):
        tag = self.package()
        with patch.object(M, 'STATE', self.d), patch.object(M, 'validate_package', return_value={}), patch.object(M, 'systemctl') as ctl:
            with self.assertRaisesRegex(ValueError, 'Approve'): M.update({}, tag, 'bad', False)
            ctl.assert_not_called()
    def test_stable_tag_filter(self):
        self.assertEqual(T.version('v3.10.2'), (3, 10, 2))
        for tag in ('dev-latest', 'v3.11.0-rc1', 'v3.10.2;evil'):
            with self.assertRaises(ValueError): T.version(tag)
    def test_shared_system_directory_rejected_before_service_stop(self):
        c = dict(panel_dir='/usr/local/x-ui', db_dir='/etc/x-ui', bin_dir='/usr/bin')
        with patch.object(M, 'systemctl') as ctl:
            with self.assertRaisesRegex(ValueError, 'Shared system'): M.validate_layout(c)
            ctl.assert_not_called()
    def test_patch_rejects_unknown_source_without_mutation(self):
        for f in P.FILES:
            p = self.d / f; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('unknown')
        with self.assertRaisesRegex(ValueError, 'Unknown'): P.apply(self.d)
        for f in P.FILES: self.assertEqual((self.d / f).read_text(), 'unknown')

    def transaction(self, failure=None, with_core=False):
        # Exercise real filesystem + SQLite transaction; mock only service,
        # native executables and HTTP unavailable on Windows CI test hosts.
        state = self.d / 'state'; state.mkdir()
        panel = self.d / 'panel'; panel.mkdir()
        core = panel / 'bin'; core.mkdir()
        dbdir = self.d / 'db'; dbdir.mkdir()
        c = dict(panel_dir=str(panel), bin_dir=str(core), db_dir=str(dbdir), unit='x-ui.service')
        (panel / 'x-ui').write_bytes(b'old panel'); (core / 'xray-linux-amd64').write_bytes(b'old core')
        (core / 'config.json').write_text('original config')
        with contextlib.closing(sqlite3.connect(dbdir / 'x-ui.db')) as db:
            db.execute('CREATE TABLE inbounds(id,port,protocol,enable,settings,stream_settings)')
            db.execute('INSERT INTO inbounds VALUES(1,443,"vless",1,?,?)', ('{"clients":[{"id":"uuid"}]}','{"security":"reality","realitySettings":{"privateKey":"KEEP"}}'))
            db.commit()
        tag = self.package(); stage = state / 'staged' / tag; stage.mkdir(parents=True)
        for n in (M.ASSET, 'manifest.json', 'SHA256SUMS'): shutil.copy2(self.d / n, stage / n)
        running = [True]; starts = []
        def ctl(action, unit):
            if action == 'stop': running[0] = False
            elif action == 'start': running[0] = True; starts.append(1)
        def command(*args, **kw):
            if args[:2] == ('systemctl', 'show'): return 'inactive'
            if args[:2] == ('systemctl', 'cat'): return 'unit sandbox'
            return '3.10.2' if 'payload' in str(args[0]) else '3.10.0'
        # Staged executable is under a random temp directory, so inspect path.
        def cmd(*args, **kw):
            if 'version' in args: return 'Xray 26.10.10'
            if str(args[0]).endswith('/x-ui') or str(args[0]).endswith('\\x-ui'):
                return '3.10.0' if Path(args[0]) == panel / 'x-ui' else '3.10.2'
            return command(*args, **kw)
        def health(*a, **kw):
            if kw.get('policy') and failure:
                with contextlib.closing(sqlite3.connect(dbdir / 'x-ui.db')) as db:
                    db.execute('UPDATE inbounds SET port=8443'); db.commit()
                (core / 'config.json').write_text('new incompatible config')
                raise failure
        # OS ownership checks and native service behavior require real-server
        # acceptance; this regression exercises file/SQLite recovery behavior.
        with patch.object(M, 'STATE', state), patch.object(M, 'run', side_effect=cmd), patch.object(M, 'systemctl', side_effect=ctl), \
             patch.object(M, 'preflight'), patch.object(M, 'healthy', side_effect=health), patch.object(M, 'xray_test'), \
             patch.object(M.os, 'chown', create=True), patch.object(M.time, 'sleep'), \
             patch.object(M, 'private'):
            if failure:
                with self.assertRaises(type(failure)): M.update(c, tag, M.sha(stage / M.ASSET), with_core)
            else: M.update(c, tag, M.sha(stage / M.ASSET), with_core)
        self.assertTrue(running[0])
        if failure:
            self.assertEqual((panel / 'x-ui').read_bytes(), b'old panel')
            self.assertEqual((core / 'config.json').read_text(), 'original config')
            with contextlib.closing(sqlite3.connect(dbdir / 'x-ui.db')) as db: self.assertEqual(db.execute('SELECT port FROM inbounds').fetchone()[0], 443)
        self.assertEqual((core / 'xray-linux-amd64').read_bytes(), b'old core' if failure or not with_core else (b'\x7fELF\x02\x01' + b'\0' * 12 + b'\x3e\x00' + b'x' * 50))
        self.assertFalse((state / 'pending.json').exists())
    def test_failed_health_restores_binary_wal_database_and_config(self): self.transaction(RuntimeError('failed health'))
    def test_interrupt_restores_old_state(self): self.transaction(KeyboardInterrupt())
    def test_panel_only_keeps_xray(self): self.transaction()
    def test_explicit_core_update(self): self.transaction(with_core=True)

    def test_offline_rollback_restores_even_corrupted_current_database(self):
        state = self.d / 'state'; state.mkdir()
        panel = self.d / 'panel'; panel.mkdir()
        core = panel / 'bin'; core.mkdir()
        dbdir = self.d / 'db'; dbdir.mkdir()
        c = dict(panel_dir=str(panel), bin_dir=str(core), db_dir=str(dbdir), unit='x-ui.service')
        (panel / 'x-ui').write_bytes(b'good panel'); (core / 'config.json').write_text('good config')
        with contextlib.closing(sqlite3.connect(dbdir / 'x-ui.db')) as db:
            db.execute('CREATE TABLE t(n)'); db.execute('INSERT INTO t VALUES(7)'); db.commit()
        def cmd(*args, **kw):
            return 'inactive' if args[:2] == ('systemctl', 'show') else 'sandbox'
        with patch.object(M, 'STATE', state), patch.object(M, 'run', side_effect=cmd), patch.object(M, 'private'), \
             patch.object(M.os, 'chown', create=True), patch.object(M, 'systemctl') as ctl, patch.object(M, 'healthy'):
            backup = M.snapshot(c, 'known-good')
            (panel / 'x-ui').write_bytes(b'broken'); (core / 'config.json').write_text('bad config')
            (dbdir / 'x-ui.db').write_bytes(b'not a database')
            M.rollback(c, backup)
            ctl.assert_any_call('start', 'x-ui.service')
        self.assertEqual((panel / 'x-ui').read_bytes(), b'good panel')
        self.assertEqual((core / 'config.json').read_text(), 'good config')
        with contextlib.closing(sqlite3.connect(dbdir / 'x-ui.db')) as db:
            self.assertEqual(db.execute('SELECT n FROM t').fetchone(), (7,))

    def test_new_sponsor_entry_point_stops_patch(self):
        profiles = json.loads((P.HERE / 'profiles.json').read_text())
        for f in P.FILES:
            p = self.d / f; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('original sponsor')
        profile = copy.deepcopy(profiles[0])
        profile['files'] = {f:P.digest('original sponsor') for f in P.FILES}
        profile['translations'] = {}
        profile['inventory'] = P.inventory(self.d)
        (self.d / 'frontend/src/new-sponsored.ts').write_text('sponsor new entry point')
        with patch.object(P.json, 'loads', return_value=[profile]):
            with self.assertRaisesRegex(ValueError, 'Unknown'): P.apply(self.d)
        for f in P.FILES: self.assertEqual((self.d / f).read_text(), 'original sponsor')

if __name__ == '__main__': unittest.main()
