#!/usr/bin/env python3
"""Debian/systemd existing-install updater. Root operator approves an archive hash.
No upstream installer, no systemd edits, no database CLI mutation, no SSH secret.
"""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.parse
import urllib.request

CONFIG = Path('/etc/x-ui-maintainer.json')
STATE = Path('/var/lib/x-ui-maintainer')
REPO = 'aishuishuishui277/3x-ui'
ASSET = 'x-ui-panel-linux-amd64.tar.gz'
TAG = re.compile(r'v\d+\.\d+\.\d+-ns\d+')

def run(*args, **kw):
    return subprocess.check_output(list(map(str, args)), text=True, stderr=subprocess.STDOUT, timeout=60, **kw).strip()

def sha(p):
    with open(p, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def write_json(path, value):
    tmp = path.with_name(path.name + '.new')
    with open(tmp, 'w') as f:
        f.write(json.dumps(value, indent=2) + '\n')
        f.flush(); os.fsync(f.fileno())
    tmp.chmod(0o600)
    os.replace(tmp, path)
    sync_directory(path.parent)

def sync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)

def private(path):
    s = path.stat()
    if s.st_uid != 0 or s.st_mode & 0o022:
        raise ValueError('Root-owned, non-writable-by-others path required: ' + str(path))

def systemctl(action, unit='x-ui.service'):
    return run('systemctl', action, unit)

def runtime(unit):
    if systemctl('is-active', unit) != 'active':
        raise ValueError('Service must already be active')
    pid = int(run('systemctl', 'show', unit, '--property=MainPID', '--value'))
    if pid < 2:
        raise ValueError('No service main process')
    status = (Path('/proc') / str(pid) / 'status').read_text()
    if re.search(r'^Uid:\s+0\s+0\s+0\s+0\s*$', status, re.M) is None:
        raise ValueError('This updater supports the original root-run service only')
    env = {}
    for item in (Path('/proc') / str(pid) / 'environ').read_bytes().split(b'\0'):
        if b'=' in item:
            k, v = item.split(b'=', 1); env[k.decode()] = v.decode()
    if env.get('XUI_DB_TYPE', 'sqlite').lower() not in ('', 'sqlite'):
        raise ValueError('This updater is for SQLite only')
    cwd = (Path('/proc') / str(pid) / 'cwd').resolve()
    exe = (Path('/proc') / str(pid) / 'exe').resolve()
    def resolve(value):
        return str((cwd / value).resolve())
    return dict(panel_dir=str(exe.parent), db_dir=resolve(env.get('XUI_DB_FOLDER', '/etc/x-ui')),
                bin_dir=resolve(env.get('XUI_BIN_FOLDER', 'bin')), exe=str(exe), unit=unit)

def load_config():
    private(CONFIG)
    c = json.loads(CONFIG.read_text())
    if c['repo'] != REPO:
        raise ValueError('Unexpected repository')
    for k in ('panel_dir', 'db_dir', 'bin_dir'):
        p = Path(c[k])
        if not p.is_absolute() or p.is_symlink() or not p.is_dir() or str(p.resolve()) != str(p):
            raise ValueError('Unsupported path: ' + k)
        private(p)
    validate_layout(c)
    return c

def validate_layout(c):
    # Never treat a shared system directory as a private application store:
    # rollback replaces store contents, so these paths must fail before stop.
    reserved = {Path(p).resolve() for p in ('/', '/etc', '/etc/default', '/etc/ssh', '/etc/ssl',
        '/etc/ssl/private', '/etc/systemd', '/etc/systemd/system', '/usr', '/usr/local',
        '/usr/bin', '/usr/sbin', '/bin', '/sbin', '/lib', '/lib64', '/var', '/var/lib',
        '/opt', '/root', '/root/.ssh', '/home')}
    if any(Path(c[k]).resolve() in reserved for k in ('panel_dir', 'db_dir', 'bin_dir')):
        raise ValueError('Shared system directories cannot be installation stores')
    panel, db, core = (Path(c[k]) for k in ('panel_dir', 'db_dir', 'bin_dir'))
    if core == panel or panel.is_relative_to(core) or db.is_relative_to(core) or core.is_relative_to(db) or panel.is_relative_to(db) or db.is_relative_to(panel):
        raise ValueError('Overlapping installation directories are unsupported')
    for p in (panel, db, core):
        if STATE.is_relative_to(p) or p.is_relative_to(STATE) or p == Path('/'):
            raise ValueError('Installation and backup paths overlap')

def db_file(c):
    return Path(c['db_dir']) / 'x-ui.db'

@contextlib.contextmanager
def connection(path):
    with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=20)) as db:
        yield db

def integrity(path):
    with connection(path) as db:
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite quick_check failed')

def backup_sqlite(source, target):
    # SQLite Backup API includes committed WAL pages; never copy only live .db.
    with connection(source) as src, contextlib.closing(sqlite3.connect(target)) as dst:
        src.backup(dst)
    shutil.copystat(source, target)
    s = source.stat()
    if hasattr(os, 'chown'): os.chown(target, s.st_uid, s.st_gid)
    integrity(target)

def reality_signature(path):
    with connection(path) as db:
        rows = db.execute('SELECT id, port, protocol, enable, settings, stream_settings FROM inbounds ORDER BY id').fetchall()
    values = []
    for ident, port, proto, enabled, settings, stream in rows:
        stream = json.loads(stream or '{}')
        if str(stream.get('security', '')).lower() == 'reality':
            values.append([ident, port, proto, enabled, json.loads(settings or '{}'), stream])
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest(), len(values)

def curl(c, suffix=''):
    url = c['health_url'] + suffix
    args = ['curl', '--fail', '--silent', '--show-error', '--max-time', '8', '--noproxy', '*']
    if c.get('resolve'):
        args += ['--resolve', c['resolve']]
    # No -k: a TLS-to-plain-HTTP fallback must fail health checks.
    return run(*args, url)

def xray_test(c):
    core = Path(c['bin_dir']) / 'xray-linux-amd64'
    cfg = Path(c['bin_dir']) / 'config.json'
    if not core.is_file() or not cfg.is_file():
        raise ValueError('Existing Xray binary/config.json missing')
    env = dict(os.environ, XRAY_LOCATION_ASSET=c['bin_dir'])
    run(core, 'run', '-test', '-config', cfg, cwd=c['panel_dir'], env=env)

def core_running(c):
    expected = (Path(c['bin_dir']) / 'xray-linux-amd64').resolve()
    main = int(run('systemctl', 'show', c['unit'], '--property=MainPID', '--value'))
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try:
            if (proc / 'exe').resolve() == expected:
                status = (proc / 'status').read_text()
                if int(re.search(r'^PPid:\s+(\d+)', status, re.M)[1]) == main:
                    return True
        except (OSError, ValueError, TypeError):
            continue
    return False

def healthy(c, policy=False, attempts=1):
    error = None
    for _ in range(attempts):
        try:
            if systemctl('is-active', c['unit']) != 'active':
                raise ValueError('Service inactive')
            if '<html' not in curl(c).lower():
                raise ValueError('Login HTML missing')
            if policy:
                obj = json.loads(curl(c, 'sponsors'))
                if not obj.get('success') or obj.get('obj') != {'sponsors': []}:
                    raise ValueError('Sponsor policy mismatch')
            if not core_running(c):
                raise ValueError('Xray child process missing')
            return
        except Exception as e:
            error = e
            if attempts > 1: time.sleep(2)
    raise RuntimeError('Health check failed: ' + str(error))

def preflight(c):
    live = runtime(c['unit'])
    for k in ('panel_dir', 'db_dir', 'bin_dir'):
        if live[k] != c[k]:
            raise ValueError('Runtime path drift: ' + k + '; run init again after review')
    if live['exe'] != str(Path(c['panel_dir']) / 'x-ui'):
        raise ValueError('Unexpected main executable')
    kill_mode = run('systemctl', 'show', c['unit'], '--property=KillMode', '--value')
    if kill_mode not in ('control-group', 'mixed'):
        raise ValueError('Service stop must terminate all children; unsupported KillMode: ' + kill_mode)
    for p in (db_file(c), Path(c['panel_dir']) / 'x-ui', Path(c['bin_dir']) / 'xray-linux-amd64'):
        if p.is_symlink(): raise ValueError('Symlink not supported: ' + str(p))
    integrity(db_file(c))
    xray_test(c)
    healthy(c)
    available = shutil.disk_usage(STATE).free
    required = sum(p.stat().st_size for d in (c['panel_dir'], c['db_dir'], c['bin_dir'])
                   for p in Path(d).rglob('*') if p.is_file())
    if available < required * 3 + 512 * 1024**2:
        raise ValueError('Insufficient backup/staging space')

def fetch(url, target):
    # HTTPS with CA validation; a checksum is an integrity check within this
    # GitHub trust boundary, not an independent publisher signature.
    req = urllib.request.Request(url, headers={'User-Agent': 'xui-no-sponsor-maintainer'})
    with urllib.request.urlopen(req, timeout=120) as r, open(target, 'wb') as f:
        shutil.copyfileobj(r, f)

def latest():
    req = urllib.request.Request(f'https://api.github.com/repos/{REPO}/releases?per_page=100',
                                 headers={'User-Agent': 'xui-no-sponsor-maintainer'})
    with urllib.request.urlopen(req, timeout=30) as r: releases = json.load(r)
    tags = [r['tag_name'] for r in releases if not r['draft'] and not r['prerelease'] and TAG.fullmatch(r['tag_name'])]
    if not tags: raise ValueError('No published no-sponsor build')
    return max(tags, key=lambda t: tuple(map(int, re.findall(r'\d+', t))))

def stage(tag):
    if tag == 'latest': tag = latest()
    if not TAG.fullmatch(tag): raise ValueError('Invalid no-sponsor tag')
    final = STATE / 'staged' / tag
    final.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=final.parent) as tmp:
        d = Path(tmp)
        url = f'https://github.com/{REPO}/releases/download/{tag}/'
        for name in (ASSET, 'SHA256SUMS', 'manifest.json'):
            fetch(url + name, d / name)
        validate_package(d, tag)
        if final.exists(): shutil.rmtree(final)
        shutil.copytree(d, final)
    return tag, final

def validate_package(d, tag):
    sums = {}
    for line in (d / 'SHA256SUMS').read_text().splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r'[0-9a-f]{64}', parts[0]):
            raise ValueError('Malformed checksums')
        if parts[1] in sums: raise ValueError('Duplicate checksum')
        sums[parts[1]] = parts[0]
    for n in (ASSET, 'manifest.json'):
        if sha(d / n) != sums.get(n): raise ValueError('SHA256 mismatch: ' + n)
    manifest = json.loads((d / 'manifest.json').read_text())
    if manifest['schema'] != 1 or manifest['architecture'] != 'linux-amd64' or manifest['release_tag'] != tag:
        raise ValueError('Manifest target mismatch')
    allowed = {'x-ui', 'x-ui/bin', 'x-ui/x-ui', 'x-ui/bin/xray-linux-amd64', 'x-ui/manifest.json', 'x-ui/LICENSE'}
    seen = set()
    with tarfile.open(d / ASSET) as t:
        total = 0
        for entry in t:
            if entry.name not in allowed or entry.name in seen or not (entry.isfile() or entry.isdir()):
                raise ValueError('Unexpected/unsafe archive member: ' + entry.name)
            seen.add(entry.name); total += entry.size
            if total > 500_000_000: raise ValueError('Archive too large')
            if entry.name in ('x-ui/x-ui', 'x-ui/bin/xray-linux-amd64'):
                with t.extractfile(entry) as f:
                    b = f.read()
                if b[:4] != b'\x7fELF' or b[4:6] != b'\x02\x01' or b[18:20] != b'\x3e\x00':
                    raise ValueError('Not ELF64 little-endian AMD64')
                key = 'panel_sha256' if entry.name == 'x-ui/x-ui' else 'xray_sha256'
                if hashlib.sha256(b).hexdigest() != manifest[key]: raise ValueError('Payload hash mismatch')
            if entry.name == 'x-ui/manifest.json':
                with t.extractfile(entry) as f:
                    if json.load(f) != manifest: raise ValueError('Embedded manifest mismatch')
    if seen != allowed: raise ValueError('Incomplete archive')
    return manifest

def atomic_copy(src, dst, mode=None):
    tmp = dst.with_name(dst.name + '.maint-new')
    shutil.copy2(src, tmp)
    s = dst.stat() if dst.exists() else src.stat()
    os.chown(tmp, s.st_uid, s.st_gid)
    if mode is not None: tmp.chmod(mode)
    with open(tmp, 'rb+') as f: os.fsync(f.fileno())
    os.replace(tmp, dst)
    sync_directory(dst.parent)

def snapshot(c, label):
    ident = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + label + '-' + os.urandom(3).hex()
    d = STATE / 'backups' / ident; d.mkdir(parents=True, mode=0o700)
    shutil.copy2(Path(c['panel_dir']) / 'x-ui', d / 'x-ui')
    backup_sqlite(db_file(c), d / 'x-ui.db')
    shutil.copytree(c['bin_dir'], d / 'bin', symlinks=True)
    # Auxiliary keys/state are part of the DB folder; don't retain stale WAL on restore.
    shutil.copytree(c['db_dir'], d / 'db-extra', symlinks=True,
                    ignore=shutil.ignore_patterns('x-ui.db', 'x-ui.db-wal', 'x-ui.db-shm'))
    (d / 'systemd.txt').write_text(run('systemctl', 'cat', c['unit']))
    (d / 'sandbox.txt').write_text(run('systemctl', 'show', c['unit'], '--property=ProtectSystem,ReadWritePaths,ReadWriteDirectories,NoNewPrivileges'))
    write_json(d / 'config.json', c)
    for p in d.rglob('*'):
        if p.is_file() and not p.is_symlink():
            with open(p, 'rb+') as f: os.fsync(f.fileno())
        elif p.is_dir() and not p.is_symlink(): sync_directory(p)
    hashes = {p.relative_to(d).as_posix(): sha(p) for p in d.rglob('*') if p.is_file() and not p.is_symlink()}
    write_json(d / 'backup-hashes.json', hashes)
    sync_directory(d.parent)
    return d

def verify_backup(d, c):
    if d.parent != STATE / 'backups' or not d.is_dir() or d.is_symlink():
        raise ValueError('Invalid backup ID')
    private(d)
    old = json.loads((d / 'config.json').read_text())
    for k in ('panel_dir', 'db_dir', 'bin_dir', 'unit'):
        if old[k] != c[k]: raise ValueError('Backup paths do not match current configuration')
    for rel, digest in json.loads((d / 'backup-hashes.json').read_text()).items():
        p = d / rel
        if not p.resolve().is_relative_to(d.resolve()) or sha(p) != digest:
            raise ValueError('Backup integrity failed')
    integrity(d / 'x-ui.db')

def restore(d, c):
    verify_backup(d, c)
    atomic_copy(d / 'x-ui', Path(c['panel_dir']) / 'x-ui')
    for suffix in ('-wal', '-shm'):
        (Path(str(db_file(c)) + suffix)).unlink(missing_ok=True)
    atomic_copy(d / 'x-ui.db', db_file(c))
    # Restore exact pre-upgrade core/config/geo and auxiliary DB state.
    # Only contents of the validated configured directories are replaced.
    for name, destination in (('bin', c['bin_dir']), ('db-extra', c['db_dir'])):
        dest = Path(destination)
        for p in dest.iterdir():
            if name == 'db-extra' and p.name in ('x-ui.db', 'x-ui.db-wal', 'x-ui.db-shm'): continue
            if p.is_dir() and not p.is_symlink(): shutil.rmtree(p)
            else: p.unlink()
        shutil.copytree(d / name, dest, dirs_exist_ok=True, symlinks=True)

@contextlib.contextmanager
def stopped(c):
    # Install the transaction's restore handlers BEFORE stopping; a failed stop
    # must not permit file mutation while the service is still running.
    systemctl('stop', c['unit'])
    state = run('systemctl', 'show', c['unit'], '--property=ActiveState', '--value')
    if state != 'inactive': raise ValueError('Service did not stop cleanly')
    yield

def rollback(c, d):
    verify_backup(d, c)
    # A rollback must also work when the broken service cannot start.
    # Save raw current files for diagnosis before restoring the known-good DB.
    rescue = STATE / ('rescue-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + os.urandom(3).hex())
    try:
        with stopped(c):
            rescue.mkdir(mode=0o700)
            shutil.copy2(Path(c['panel_dir']) / 'x-ui', rescue / 'x-ui')
            shutil.copytree(c['db_dir'], rescue / 'db', symlinks=True)
            shutil.copytree(c['bin_dir'], rescue / 'bin', symlinks=True)
            restore(d, c)
        systemctl('start', c['unit'])
        healthy(c, attempts=30)
    except BaseException:
        # Leave the validated restored backup in place if its health check
        # fails (e.g. external cert/path problem). Never silently put the known
        # broken deployment back. The rescue copy is retained for diagnosis.
        print('Rollback needs inspection; known-good backup and rescue copy retained:', rescue, file=sys.stderr)
        raise
    (STATE / 'installed.json').unlink(missing_ok=True)
    print('Restored:', d.name, '; previous state saved:', rescue.name)

def update(c, tag, approved, with_core):
    if (STATE / 'pending.json').exists():
        raise ValueError('Unfinished update: inspect pending.json and use recover --approve-rollback')
    if not TAG.fullmatch(tag): raise ValueError('Explicit staged tag required')
    d = STATE / 'staged' / tag
    manifest = validate_package(d, tag)
    if not re.fullmatch('[0-9a-f]{64}', approved or '') or sha(d / ASSET) != approved:
        raise ValueError('Approve the exact SHA256 printed by check')
    preflight(c)
    installed = run(Path(c['panel_dir']) / 'x-ui', '-v').lstrip('v')
    target = manifest['tag'].lstrip('v')
    if tuple(map(int, target.split('.'))) < tuple(map(int, installed.split('.'))):
        raise ValueError('Use rollback for downgrade')
    before_reality = reality_signature(db_file(c))
    core_path = Path(c['bin_dir']) / 'xray-linux-amd64'
    old_core = sha(core_path)
    with tempfile.TemporaryDirectory(dir=STATE) as tmp:
        payload = Path(tmp)
        with tarfile.open(d / ASSET) as t:
            # validate_package already rejects links, duplicate paths, traversal.
            t.extractall(payload, filter='data')
        if run(payload / 'x-ui/x-ui', '-v').lstrip('v') != target:
            raise ValueError('Panel version mismatch')
        if with_core:
            env = dict(os.environ, XRAY_LOCATION_ASSET=c['bin_dir'])
            run(payload / 'x-ui/bin/xray-linux-amd64', 'run', '-test', '-config', Path(c['bin_dir']) / 'config.json', env=env)
        backup = None
        try:
            with stopped(c):
                backup = snapshot(c, 'before-' + tag)
                write_json(STATE / 'pending.json', dict(backup=backup.name, tag=tag))
                print('Rollback backup:', backup.name, flush=True)
                atomic_copy(payload / 'x-ui/x-ui', Path(c['panel_dir']) / 'x-ui', 0o755)
                if with_core: atomic_copy(payload / 'x-ui/bin/xray-linux-amd64', core_path, 0o755)
            systemctl('start', c['unit'])
            healthy(c, policy=True, attempts=30)
            integrity(db_file(c))
            if reality_signature(db_file(c)) != before_reality:
                raise ValueError('Reality inbound settings changed')
            xray_test(c)
            if not with_core and sha(core_path) != old_core:
                raise ValueError('Xray changed during panel-only update')
            time.sleep(10)
            healthy(c, policy=True)
            write_json(STATE / 'installed.json', dict(manifest, rollback=backup.name))
            (STATE / 'pending.json').unlink(missing_ok=True)
            print('Update passed local checks. Test the Reality client externally; rollback:', backup.name)
        except BaseException:
            if backup and (backup / 'backup-hashes.json').exists():
                systemctl('stop', c['unit'])
                restore(backup, c)
            systemctl('start', c['unit'])
            healthy(c, attempts=15)
            (STATE / 'pending.json').unlink(missing_ok=True)
            raise

def init(args):
    c = runtime(args.unit)
    if c['exe'] != str(Path(c['panel_dir']) / 'x-ui'): raise ValueError('Unexpected executable')
    c.pop('exe')
    validate_layout(c)
    u = urllib.parse.urlsplit(args.health_url)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.password or u.query or u.fragment or not u.path.endswith('/'):
        raise ValueError('health URL must include base path and trailing /; no credentials/query')
    if u.scheme == 'http' and u.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Plain HTTP health URL must be loopback')
    c.update(repo=REPO, health_url=args.health_url, resolve=args.resolve)
    healthy(c)
    integrity(db_file(c))
    xray_test(c)
    write_json(CONFIG, c)
    print('Configuration saved; service unchanged. Review with: xui-maintain inspect')

def main():
    if sys.platform != 'linux' or os.geteuid() != 0: raise ValueError('Run as root on Debian x86_64')
    if os.uname().machine != 'x86_64': raise ValueError('Only x86_64 supported')
    if not hasattr(tarfile, 'data_filter'): raise ValueError('Install the current Debian Python security updates first')
    os.umask(0o077)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    private(STATE)
    import fcntl
    with open(STATE / 'lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        parser = argparse.ArgumentParser(description=__doc__)
        sub = parser.add_subparsers(dest='command', required=True)
        p = sub.add_parser('init'); p.add_argument('--unit', default='x-ui.service'); p.add_argument('--health-url', required=True); p.add_argument('--resolve', default='')
        sub.add_parser('inspect')
        p = sub.add_parser('check'); p.add_argument('tag', nargs='?', default='latest')
        p = sub.add_parser('update'); p.add_argument('tag'); p.add_argument('--approve', required=True); p.add_argument('--with-bundled-xray', action='store_true')
        p = sub.add_parser('rollback'); p.add_argument('backup_id'); p.add_argument('--approve-rollback', action='store_true', required=True)
        p = sub.add_parser('recover'); p.add_argument('--approve-rollback', action='store_true', required=True)
        sub.add_parser('backups')
        args = parser.parse_args()
        if args.command == 'init': init(args); return
        c = load_config()
        def interrupt(signum, frame): raise KeyboardInterrupt('Interrupted; attempting recovery')
        signal.signal(signal.SIGTERM, interrupt)
        if args.command == 'inspect':
            preflight(c)
            print(json.dumps({k: c[k] for k in ('unit', 'panel_dir', 'db_dir', 'bin_dir')}, indent=2))
            print(run('systemctl', 'show', c['unit'], '--property=ProtectSystem,ReadWritePaths,NoNewPrivileges'))
            print('Reality inbound count:', reality_signature(db_file(c))[1])
            print('Panel:', run(Path(c['panel_dir']) / 'x-ui', '-v'))
            print('Xray:', run(Path(c['bin_dir']) / 'xray-linux-amd64', 'version').splitlines()[0])
        elif args.command == 'check':
            preflight(c)
            tag, d = stage(args.tag)
            print('Staged:', tag, '\nSHA256:', sha(d / ASSET))
            print('Approve panel-only update with:\nsudo xui-maintain update', tag, '--approve', sha(d / ASSET))
        elif args.command == 'update': update(c, args.tag, args.approve, args.with_bundled_xray)
        elif args.command == 'backups':
            for p in sorted((STATE / 'backups').glob('*')): print(p.name)
        elif args.command == 'rollback':
            if not re.fullmatch(r'[A-Za-z0-9.-]+', args.backup_id): raise ValueError('Invalid backup ID')
            d = STATE / 'backups' / args.backup_id
            rollback(c, d)
            (STATE / 'pending.json').unlink(missing_ok=True)
        elif args.command == 'recover':
            pending = json.loads((STATE / 'pending.json').read_text())
            ident = pending['backup']
            if not re.fullmatch(r'[A-Za-z0-9.-]+', ident): raise ValueError('Invalid pending backup')
            rollback(c, STATE / 'backups' / ident)
            (STATE / 'pending.json').unlink(missing_ok=True)

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print('STOP:', str(e), file=sys.stderr); sys.exit(1)
