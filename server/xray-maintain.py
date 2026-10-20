#!/usr/bin/env python3
"""Core-only companion to xui-maintain. Same configuration/lock, independent approval.
Rollback restores only the executable: never roll back SQLite/WAL or geo data.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import tarfile
import tempfile
import time
import urllib.request
from importlib.machinery import SourceFileLoader

helper = Path(__file__).with_name('xui-maintain.py')
if not helper.exists(): helper = Path(__file__).with_name('xui-maintain')
spec = importlib.util.spec_from_loader('xui_shared', SourceFileLoader('xui_shared', str(helper)))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
TAG = re.compile(r'xray-v(\d+)\.(\d+)\.(\d+)-r(\d+)')
ASSET = 'xray-linux-amd64.tar.gz'

def version(text):
    match = re.search(r'^Xray (\d+)\.(\d+)\.(\d+)\b', text)
    if not match: raise ValueError('Unrecognized Xray binary version')
    return tuple(map(int, match.groups()))

def binary(c): return Path(c['bin_dir']) / 'xray-linux-amd64'

def current(c): return version(M.run(binary(c), 'version'))

def latest(channel):
    req = urllib.request.Request(f'https://api.github.com/repos/{M.REPO}/releases?per_page=100',
                                 headers={'User-Agent':'xui-xray-maintainer'})
    with urllib.request.urlopen(req, timeout=30) as r: releases = json.load(r)
    choices = [r['tag_name'] for r in releases if not r['draft'] and TAG.fullmatch(r['tag_name'])
               and (channel == 'preview' or not r['prerelease'])]
    if not choices: return None
    return max(choices, key=lambda t: tuple(map(int, TAG.fullmatch(t).groups())))

def validate(d, tag):
    if not TAG.fullmatch(tag): raise ValueError('Invalid core release tag')
    sums = {}
    for line in (d / 'XRAY-SHA256SUMS').read_text().splitlines():
        p = line.split()
        if len(p) != 2 or not re.fullmatch('[0-9a-f]{64}', p[0]) or p[1] in sums:
            raise ValueError('Malformed/duplicate core checksum')
        sums[p[1]] = p[0]
    for n in (ASSET, 'xray-manifest.json', 'xray-validation.json'):
        if M.sha(d / n) != sums.get(n): raise ValueError('Core SHA256 mismatch: ' + n)
    obj = json.loads((d / 'xray-manifest.json').read_text())
    if (obj.get('schema'), obj.get('kind'), obj.get('architecture'), obj.get('release_tag'), obj.get('upstream')) != (
            1, 'xray-core', 'linux-amd64', tag, 'XTLS/Xray-core'):
        raise ValueError('Core manifest target mismatch')
    if obj['tag'] != 'v' + '.'.join(TAG.fullmatch(tag).groups()[:3]) or type(obj['upstream_prerelease']) is not bool:
        raise ValueError('Core version/channel mismatch')
    result = json.loads((d / 'xray-validation.json').read_text())
    if (result.get('official_sha256') != 'passed' or result.get('elf_amd64') != 'passed'
            or result.get('binary_version') != 'passed' or len(result.get('reality_vision_loopback', [])) != 2):
        raise ValueError('Core validation report incomplete')
    allowed = {'xray-linux-amd64', 'LICENSE', 'xray-manifest.json'}; seen = set(); total = 0
    with tarfile.open(d / ASSET) as t:
        for e in t:
            if e.name not in allowed or e.name in seen or not e.isfile():
                raise ValueError('Unsafe core archive member')
            seen.add(e.name); total += e.size
            if total > 150_000_000: raise ValueError('Core archive too large')
            with t.extractfile(e) as f: data = f.read()
            if e.name == 'xray-linux-amd64':
                if data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\x3e\x00':
                    raise ValueError('Not Linux ELF64 AMD64')
                if hashlib.sha256(data).hexdigest() != obj['xray_sha256']: raise ValueError('Core payload hash mismatch')
            elif e.name == 'xray-manifest.json' and json.loads(data) != obj:
                raise ValueError('Embedded core manifest mismatch')
    if seen != allowed: raise ValueError('Incomplete core archive')
    return obj

def stage(tag):
    if not TAG.fullmatch(tag): raise ValueError('Invalid core release tag')
    final = M.STATE / 'core-staged' / tag
    final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=final.parent) as tmp:
        d = Path(tmp)
        for name in (ASSET, 'xray-manifest.json', 'xray-validation.json', 'XRAY-SHA256SUMS'):
            M.fetch(f'https://github.com/{M.REPO}/releases/download/{tag}/{name}', d / name)
        validate(d, tag)
        if final.exists(): shutil.rmtree(final)
        shutil.copytree(d, final)
    return final

def test(c, candidate):
    env = dict(os.environ, XRAY_LOCATION_ASSET=c['bin_dir'])
    M.run(candidate, 'run', '-test', '-config', Path(c['bin_dir']) / 'config.json', env=env)

def no_pending():
    if (M.STATE / 'pending.json').exists(): raise ValueError('Unfinished transaction: recover it before another update')

def snapshot(c):
    ident = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-core-' + os.urandom(3).hex()
    d = M.STATE / 'core-backups' / ident; d.mkdir(parents=True, mode=0o700)
    shutil.copy2(binary(c), d / 'xray-linux-amd64')
    # Record the generated configuration for diagnosis only; do not restore it
    # over database-derived configuration on a core rollback.
    shutil.copy2(Path(c['bin_dir']) / 'config.json', d / 'config-at-update.json')
    M.write_json(d / 'backup.json', dict(kind='core', unit=c['unit'], bin_dir=c['bin_dir'],
        panel_dir=c['panel_dir'], db_dir=c['db_dir'], sha256=M.sha(d / 'xray-linux-amd64'), version=list(current(c))))
    for p in d.iterdir():
        with open(p, 'rb+') as f: os.fsync(f.fileno())
    M.sync_directory(d); M.sync_directory(d.parent)
    return d

def verify_backup(c, d):
    if d.parent != M.STATE / 'core-backups' or not d.is_dir() or d.is_symlink(): raise ValueError('Invalid core backup')
    M.private(d)
    obj = json.loads((d / 'backup.json').read_text())
    if obj.get('kind') != 'core' or any(obj[k] != c[k] for k in ('unit','bin_dir','panel_dir','db_dir')):
        raise ValueError('Core backup installation mismatch')
    old = d / 'xray-linux-amd64'
    if old.is_symlink() or M.sha(old) != obj['sha256']: raise ValueError('Core backup SHA256 mismatch')
    return obj

def restore(c, d):
    verify_backup(c, d)
    M.atomic_copy(d / 'xray-linux-amd64', binary(c), 0o755)

def update(c, tag, approved, allow_preview=False):
    no_pending()
    d = M.STATE / 'core-staged' / tag
    obj = validate(d, tag)
    if not re.fullmatch('[0-9a-f]{64}', approved or '') or M.sha(d / ASSET) != approved:
        raise ValueError('Approve the exact core SHA256 printed by check')
    if obj['upstream_prerelease'] and not allow_preview: raise ValueError('Official prerelease requires --allow-prerelease')
    M.preflight(c)
    target = tuple(map(int, obj['tag'][1:].split('.')))
    if target <= current(c): raise ValueError('Core is already equal/newer; use core rollback for downgrade')
    before = M.reality_signature(M.db_file(c)); panel_sha = M.sha(Path(c['panel_dir']) / 'x-ui')
    backup = None
    with tempfile.TemporaryDirectory(dir=M.STATE) as tmp:
        payload = Path(tmp)
        with tarfile.open(d / ASSET) as t: t.extractall(payload, filter='data')
        candidate = payload / 'xray-linux-amd64'; candidate.chmod(0o755)
        if version(M.run(candidate, 'version')) != target: raise ValueError('Staged binary version mismatch')
        test(c, candidate)  # Active config must pass BEFORE stopping the service.
        try:
            with M.stopped(c):
                test(c, candidate)  # Repeat against final flushed config, using existing geo/certs.
                backup = snapshot(c)
                M.write_json(M.STATE / 'pending.json', dict(kind='core', backup=backup.name, tag=tag))
                print('Core rollback backup:', backup.name, flush=True)
                M.atomic_copy(candidate, binary(c), 0o755)
            M.systemctl('start', c['unit'])
            M.healthy(c, attempts=30)
            M.integrity(M.db_file(c)); M.xray_test(c)
            if M.reality_signature(M.db_file(c)) != before: raise ValueError('Reality settings changed')
            if M.sha(Path(c['panel_dir']) / 'x-ui') != panel_sha or M.sha(binary(c)) != obj['xray_sha256']:
                raise ValueError('Panel/core file drift')
            if current(c) != target: raise ValueError('Installed core version mismatch')
            time.sleep(15); M.healthy(c)
            M.write_json(M.STATE / 'core-installed.json', dict(obj, rollback=backup.name))
            (M.STATE / 'pending.json').unlink(); M.sync_directory(M.STATE)
            print('Core update passed local checks. Verify Reality from your client. Rollback:', backup.name)
        except BaseException:
            if backup:
                with M.stopped(c): restore(c, backup)
            M.systemctl('start', c['unit']); M.healthy(c, attempts=15)
            (M.STATE / 'pending.json').unlink(missing_ok=True)
            raise

def rollback(c, d):
    obj = verify_backup(c, d)
    if binary(c).is_symlink(): raise ValueError('Core symlink unsupported')
    # Does not need the failed service to be active. No DB backup is restored.
    test(c, d / 'xray-linux-amd64')
    rescue = M.STATE / ('core-rescue-' + os.urandom(6).hex())
    with M.stopped(c):
        shutil.copy2(binary(c), rescue)
        restore(c, d)
    M.systemctl('start', c['unit']); M.healthy(c, attempts=30)
    if list(current(c)) != obj['version']: raise ValueError('Restored core version mismatch')
    (M.STATE / 'core-installed.json').unlink(missing_ok=True)
    print('Restored core:', d.name, '; previous binary saved:', rescue.name)

def main():
    if sys.platform != 'linux' or os.geteuid() != 0 or os.uname().machine != 'x86_64':
        raise ValueError('Run as root on Debian x86_64')
    if not hasattr(tarfile, 'data_filter'): raise ValueError('Current Python 3.11+ security updates required')
    os.umask(0o077); M.STATE.mkdir(parents=True, exist_ok=True, mode=0o700); M.private(M.STATE)
    import fcntl
    with open(M.STATE / 'lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        parser = argparse.ArgumentParser(description=__doc__)
        sub = parser.add_subparsers(dest='command', required=True)
        p = sub.add_parser('check'); p.add_argument('tag', nargs='?', default='latest'); p.add_argument('--channel', choices=['stable','preview'], default='stable')
        p = sub.add_parser('update'); p.add_argument('tag'); p.add_argument('--approve', required=True); p.add_argument('--allow-prerelease', action='store_true')
        p = sub.add_parser('rollback'); p.add_argument('backup_id'); p.add_argument('--approve-rollback', action='store_true', required=True)
        p = sub.add_parser('recover'); p.add_argument('--approve-rollback', action='store_true', required=True)
        sub.add_parser('backups')
        args = parser.parse_args(); c = M.load_config()
        def interrupt(signum, frame): raise KeyboardInterrupt('Interrupted; attempting core recovery')
        signal.signal(signal.SIGTERM, interrupt)
        if args.command == 'check':
            M.preflight(c)
            tag = latest(args.channel) if args.tag == 'latest' else args.tag
            if not tag:
                print('No eligible published core candidate. Keep current:', current(c)); return
            d = stage(tag); obj = validate(d, tag)
            if obj['upstream_prerelease'] and args.channel != 'preview': raise ValueError('Use --channel preview for official prereleases')
            target = tuple(map(int, obj['tag'][1:].split('.')))
            if target <= current(c): print('Keep current core; no upgrade:', current(c), 'candidate:', target); return
            print('Staged:', tag, '\nOfficial prerelease:', obj['upstream_prerelease'], '\nSHA256:', M.sha(d / ASSET))
            print('Approve with:\nsudo xray-maintain update', tag, '--approve', M.sha(d / ASSET),
                  '--allow-prerelease' if obj['upstream_prerelease'] else '')
        elif args.command == 'update': update(c, args.tag, args.approve, args.allow_prerelease)
        elif args.command == 'backups':
            for p in sorted((M.STATE / 'core-backups').glob('*')): print(p.name)
        else:
            if args.command == 'recover':
                pending = json.loads((M.STATE / 'pending.json').read_text())
                if pending.get('kind') != 'core': raise ValueError('Panel transaction: use xui-maintain recover')
                ident = pending['backup']
            else:
                no_pending(); ident = args.backup_id
            if not re.fullmatch(r'[A-Za-z0-9.-]+', ident): raise ValueError('Invalid core backup ID')
            rollback(c, M.STATE / 'core-backups' / ident)
            (M.STATE / 'pending.json').unlink(missing_ok=True)

if __name__ == '__main__':
    try: main()
    except Exception as e: print('STOP:', str(e), file=sys.stderr); sys.exit(1)
