import contextlib
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
C = module('core_maintainer', ROOT / 'server/xray-maintain.py')
R = module('core_release', ROOT / 'maintenance/xray_release.py')

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_release_channels_do_not_downgrade_baseline(self):
        releases = [dict(tag_name='v26.3.27', draft=False, prerelease=False),
                    dict(tag_name='v26.10.17', draft=False, prerelease=True),
                    dict(tag_name='dev-latest', draft=False, prerelease=False)]
        self.assertIsNone(R.choose(releases, 'stable'))
        self.assertEqual(R.choose(releases, 'preview')['tag_name'], 'v26.10.17')
        releases.append(dict(tag_name='v26.10.20', draft=False, prerelease=False))
        self.assertEqual(R.choose(releases, 'stable')['tag_name'], 'v26.10.20')
    def test_actual_official_digest_format_and_duplicates(self):
        h = 'a' * 64
        self.assertEqual(R.digest('MD5= xx\r\nSHA2-256= ' + h + '\r\nSHA2-512= xx\r\n'), h)
        for raw in ('SHA1= aa', 'SHA2-256= wrong', f'SHA2-256= {h}\nSHA2-256= {h}'):
            with self.assertRaises(ValueError): R.digest(raw)
    def package(self, extra=None):
        tag = 'xray-v26.10.17-r1'
        elf = b'\x7fELF\x02\x01' + b'\0' * 12 + b'\x3e\x00' + b'candidate'
        obj = dict(schema=1, kind='xray-core', architecture='linux-amd64', release_tag=tag,
                   tag='v26.10.17', upstream='XTLS/Xray-core', upstream_prerelease=True,
                   xray_sha256=hashlib.sha256(elf).hexdigest())
        (self.d / 'xray-manifest.json').write_text(json.dumps(obj))
        (self.d / 'xray-validation.json').write_text(json.dumps(dict(official_sha256='passed',elf_amd64='passed',
            binary_version='passed', reality_vision_loopback=['baseline passed','candidate passed'])))
        with tarfile.open(self.d / C.ASSET, 'w:gz') as t:
            for name, data in {'xray-linux-amd64':elf,'LICENSE':b'MIT','xray-manifest.json':json.dumps(obj).encode()}.items():
                e = tarfile.TarInfo(name); e.size = len(data); e.mode = 0o755; t.addfile(e, io.BytesIO(data))
            if extra: t.addfile(extra)
        self.sums()
        return tag, elf
    def sums(self):
        (self.d / 'XRAY-SHA256SUMS').write_text(''.join(C.M.sha(self.d / n) + '  ' + n + '\n'
            for n in (C.ASSET,'xray-manifest.json','xray-validation.json')))
    def test_archive_valid_and_tamper_rejected(self):
        tag, _ = self.package(); C.validate(self.d, tag)
        with open(self.d / C.ASSET, 'ab') as f: f.write(b'tamper')
        with self.assertRaisesRegex(ValueError, 'SHA256'): C.validate(self.d, tag)
    def test_archive_traversal_symlink_duplicate_rejected(self):
        link = tarfile.TarInfo('link'); link.type = tarfile.SYMTYPE; link.linkname = '/etc/shadow'
        for e in (tarfile.TarInfo('../xray'), link, tarfile.TarInfo('LICENSE')):
            tag, _ = self.package(e)
            with self.assertRaisesRegex(ValueError, 'Unsafe'): C.validate(self.d, tag)
    def test_pending_panel_transaction_blocks_core(self):
        (self.d / 'pending.json').write_text('{"backup":"panel"}')
        with patch.object(C.M, 'STATE', self.d), patch.object(C.M, 'systemctl') as ctl:
            with self.assertRaisesRegex(ValueError, 'Unfinished'): C.no_pending()
            ctl.assert_not_called()
    def test_panel_bundle_cannot_downgrade_newer_core(self):
        # A panel upgrade may carry the old 26.10.10 bundle after a separate
        # core upgrade. Reject that downgrade even with the explicit bundle flag.
        from test_maintenance import SafetyTests, M as P
        fixture = SafetyTests(); fixture.d = self.d
        tag = fixture.package()
        state = self.d / 'state'; stage = state / 'staged' / tag; stage.mkdir(parents=True)
        for n in (P.ASSET, 'manifest.json', 'SHA256SUMS'): shutil.copy2(self.d / n, stage / n)
        panel = self.d / 'panel'; panel.mkdir(); (panel / 'x-ui').write_bytes(b'panel')
        core = panel / 'bin'; core.mkdir(); (core / 'xray-linux-amd64').write_bytes(b'newer core')
        c = dict(panel_dir=str(panel),bin_dir=str(core),db_dir=str(self.d),unit='x-ui.service')
        def run(*args, **kw):
            if 'version' in args: return 'Xray ' + ('26.10.17' if Path(args[0]) == core / 'xray-linux-amd64' else '26.10.10')
            return '3.10.0' if Path(args[0]) == panel / 'x-ui' else '3.10.2'
        with patch.object(P, 'STATE', state), patch.object(P, 'preflight'), patch.object(P, 'run', side_effect=run), \
             patch.object(P, 'reality_signature', return_value=('unchanged',1)), patch.object(P, 'systemctl') as ctl:
            with self.assertRaisesRegex(ValueError, 'downgrade'): P.update(c, tag, P.sha(stage / P.ASSET), True)
            ctl.assert_not_called()
    def transaction(self, failure=False, approval=True, preview=True, bad_config=False, downgrade=False):
        tag, elf = self.package()
        state = self.d / 'state'; state.mkdir()
        panel = self.d / 'panel'; panel.mkdir(); (panel / 'x-ui').write_bytes(b'panel unchanged')
        core = panel / 'bin'; core.mkdir(); (core / 'xray-linux-amd64').write_bytes(b'old core')
        (core / 'config.json').write_text('{"existing":"config"}'); (core / 'geoip.dat').write_bytes(b'geo unchanged')
        dbdir = self.d / 'db'; dbdir.mkdir(); dbpath = dbdir / 'x-ui.db'
        db = sqlite3.connect(dbpath); db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE inbounds(id, port, protocol, enable, settings, stream_settings)')
        db.execute('INSERT INTO inbounds VALUES(1,443,"vless",1,?,?)',
            ('{"clients":[{"id":"uuid"}]}','{"security":"reality","realitySettings":{"privateKey":"KEEP"}}'))
        db.execute('CREATE TABLE traffic(n)'); db.execute('INSERT INTO traffic VALUES(42)'); db.commit()
        c = dict(panel_dir=str(panel),bin_dir=str(core),db_dir=str(dbdir),unit='x-ui.service')
        stage = state / 'core-staged' / tag; stage.mkdir(parents=True)
        for n in (C.ASSET,'xray-manifest.json','xray-validation.json','XRAY-SHA256SUMS'): shutil.copy2(self.d / n, stage / n)
        events = []
        def ctl(action, unit): events.append(action)
        def run(*args, **kw):
            if args[:2] == ('systemctl','show'): return 'inactive'
            if 'version' in args:
                b = Path(args[0]).read_bytes()
                return 'Xray ' + ('26.10.17' if b == elf else ('26.10.20' if downgrade else '26.10.10'))
            return ''
        def health(*a, **kw):
            if failure and (core / 'xray-linux-amd64').read_bytes() == elf:
                db.execute('UPDATE traffic SET n=99'); db.commit()
                raise RuntimeError('new core failed')
        try:
            with patch.object(C.M, 'STATE', state), patch.object(C.M, 'private'), patch.object(C.M, 'run', side_effect=run), \
                 patch.object(C.M, 'systemctl', side_effect=ctl), patch.object(C.M, 'preflight'), \
                 patch.object(C.M, 'healthy', side_effect=health), patch.object(C.M, 'xray_test'), \
                 patch.object(C.M.os, 'chown', create=True), patch.object(C.time, 'sleep'), \
                 patch.object(C, 'test', side_effect=ValueError('config invalid') if bad_config else None):
                if failure or not approval or not preview or bad_config or downgrade:
                    with self.assertRaises((ValueError, RuntimeError)):
                        C.update(c, tag, C.M.sha(stage / C.ASSET) if approval else 'bad', preview)
                    self.assertEqual((core / 'xray-linux-amd64').read_bytes(), b'old core')
                    if not failure: self.assertNotIn('stop', events)
                else:
                    C.update(c, tag, C.M.sha(stage / C.ASSET), True)
                    self.assertEqual((core / 'xray-linux-amd64').read_bytes(), elf)
                    db.execute('UPDATE traffic SET n=88'); db.commit()
                    backup = next((state / 'core-backups').iterdir())
                    C.rollback(c, backup)
                    self.assertEqual((core / 'xray-linux-amd64').read_bytes(), b'old core')
                self.assertEqual((panel / 'x-ui').read_bytes(), b'panel unchanged')
                self.assertEqual((core / 'geoip.dat').read_bytes(), b'geo unchanged')
                self.assertEqual((core / 'config.json').read_text(), '{"existing":"config"}')
                n = db.execute('SELECT n FROM traffic').fetchone()[0]
                self.assertEqual(n, 99 if failure else (88 if approval and preview and not bad_config and not downgrade else 42))
                self.assertEqual(db.execute('SELECT port FROM inbounds').fetchone()[0], 443)
                self.assertFalse((state / 'pending.json').exists())
        finally: db.close()
    def test_success_and_rollback_preserve_live_wal_traffic(self): self.transaction()
    def test_failure_recovers_core_without_restoring_sqlite(self): self.transaction(failure=True)
    def test_unapproved_hash_does_not_stop(self): self.transaction(approval=False)
    def test_prerelease_needs_explicit_flag(self): self.transaction(preview=False)
    def test_incompatible_config_rejected_before_stop(self): self.transaction(bad_config=True)
    def test_equal_or_newer_core_never_downgraded(self): self.transaction(downgrade=True)

if __name__ == '__main__': unittest.main()
