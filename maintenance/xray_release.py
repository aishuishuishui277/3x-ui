#!/usr/bin/env python3
"""Track XTLS release metadata; verify official binary, never build a modified core."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import time
import urllib.request
import zipfile
from status import blocked, emit, identity, output, release_identity

UPSTREAM = 'XTLS/Xray-core'
POLICY = json.loads(Path(__file__).with_name('xray-policy.json').read_text())
FLOOR = tuple(map(int, POLICY['minimum_candidate_version'][1:].split('.')))
ASSET = 'xray-linux-amd64.tar.gz'
TAG = re.compile(r'v\d+\.\d+\.\d+')

def version(tag):
    if not TAG.fullmatch(tag): raise ValueError('Invalid Xray tag: ' + tag)
    return tuple(map(int, tag[1:].split('.')))

def api(path):
    headers = {'User-Agent':'xui-maintenance', 'Accept':'application/vnd.github+json'}
    if os.environ.get('GH_TOKEN'): headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    with urllib.request.urlopen(urllib.request.Request('https://api.github.com/' + path, headers=headers), timeout=60) as r:
        return json.load(r)

def choose(releases, channel):
    choices = [r for r in releases if not r['draft'] and TAG.fullmatch(r['tag_name'])
               and version(r['tag_name']) >= FLOOR and (channel == 'preview' or not r['prerelease'])]
    return max(choices, key=lambda r: version(r['tag_name'])) if choices else None

def digest(text):
    values = re.findall(r'^SHA2-256=\s*([0-9a-fA-F]{64})\s*$', text, re.M)
    if len(values) != 1: raise ValueError('Exactly one official SHA2-256 entry required')
    return values[0].lower()

def sha(path):
    with open(path, 'rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def download_asset(url, target, expected_digest):
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', expected_digest or ''):
        raise ValueError('Official GitHub asset digest missing/malformed')
    if target.exists() and 'sha256:' + sha(target) == expected_digest: return
    partial = target.with_name(target.name + '.partial')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(partial, 'wb') as f:
                import shutil
                shutil.copyfileobj(r, f)
            break
        except OSError:
            partial.unlink(missing_ok=True)
            if attempt == 2: raise
            time.sleep(attempt + 1)
    if 'sha256:' + sha(partial) != expected_digest:
        partial.unlink(missing_ok=True)
        raise ValueError('Official GitHub asset SHA256 mismatch')
    partial.replace(target)

def download_verified(release, dest, pinned=None):
    """Only fetch fixed HTTPS official asset URLs, also compare API asset digest."""
    tag = release['tag_name']; version(tag)
    assets = {a['name']: a for a in release['assets']}
    for name in ('Xray-linux-64.zip', 'Xray-linux-64.zip.dgst'):
        asset = assets[name]
        expected = f'https://github.com/{UPSTREAM}/releases/download/{tag}/{name}'
        if asset['browser_download_url'] != expected: raise ValueError('Unexpected official asset URL')
        if pinned and asset.get('digest') != 'sha256:' + pinned[name]:
            raise ValueError('Reviewed baseline asset digest changed')
        target = dest / name
        download_asset(expected, target, asset.get('digest'))
        if asset.get('digest') != 'sha256:' + sha(dest / name):
            raise ValueError('Official GitHub asset SHA256 mismatch/missing')
    archive = dest / 'Xray-linux-64.zip'
    if sha(archive) != digest((dest / 'Xray-linux-64.zip.dgst').read_text()):
        raise ValueError('Official .dgst SHA256 mismatch')
    with zipfile.ZipFile(archive) as z:
        for name in ('xray', 'LICENSE'):
            entries = [i for i in z.infolist() if i.filename == name]
            if len(entries) != 1 or entries[0].file_size > 150_000_000 or entries[0].is_dir():
                raise ValueError('Missing/duplicate/oversized official payload')
            (dest / name).write_bytes(z.read(entries[0]))
    b = (dest / 'xray').read_bytes()
    if b[:6] != b'\x7fELF\x02\x01' or b[18:20] != b'\x3e\x00':
        raise ValueError('Not Linux ELF64 AMD64')
    (dest / 'xray').chmod(0o755)
    output = subprocess.check_output([str((dest / 'xray').resolve()), 'version'], text=True)
    match = re.search(r'^Xray (\d+\.\d+\.\d+)\b', output)
    if not match or 'v' + match[1] != tag: raise ValueError('Official binary version mismatch')
    return archive

def main():
    channel = os.environ.get('CHANNEL', 'stable')
    if channel not in ('stable', 'preview'): raise ValueError('Invalid channel')
    requested = os.environ.get('XRAY_TAG', '')
    if requested:
        version(requested)
        release = api(f'repos/{UPSTREAM}/releases/tags/{requested}')
        if release['draft'] or version(requested) < FLOOR:
            raise ValueError('Requested tag violates channel/baseline policy')
        if bool(release['prerelease']) != (channel == 'preview'):
            output(build='false', tag='')
            emit('NO_UPDATE', identity('xray-explicit-other-channel',requested,channel), 'Explicit tag handled by the other channel')
            return
    else:
        release = choose(api(f'repos/{UPSTREAM}/releases?per_page=100'), channel)
    target = ('xray-' + release['tag_name'] + '-r1') if release else ''
    own = api(f'repos/{os.environ["GITHUB_REPOSITORY"]}/releases?per_page=100')
    existing = next((r for r in own if r['tag_name'] == target and not r['draft']), None)
    newer = [r for r in own if re.fullmatch(r'xray-v\d+\.\d+\.\d+-r\d+', r['tag_name']) and not r['draft']
             and (channel == 'preview' or not r.get('prerelease', False))]
    required = {ASSET, 'xray-manifest.json', 'xray-validation.json', 'XRAY-SHA256SUMS'}
    if existing and not required.issubset({a['name'] for a in existing['assets']}):
        raise ValueError('Existing public core release is incomplete; manual repair required')
    key = identity('xray', release_identity(release) if release else None, POLICY, channel, requested)
    Path('attempt.json').write_text(json.dumps({'identity':key}) + '\n')
    if release and not requested and any(version(r['tag_name'].split('-r')[0][5:]) > version(release['tag_name']) for r in newer):
        output(build='false', tag=target)
        emit('REVIEW_REQUIRED', key, 'Official release selection moved backwards; no downgrade/build')
        return
    prior = blocked(key)
    # Preview means prereleases plus stable fallback for explicit local/manual
    # validation. Scheduled stable candidates are handled once by stable job.
    covered = channel == 'preview' and release and not release['prerelease'] and not requested
    build = release is not None and (existing is None or os.environ.get('FORCE_VALIDATE') == 'true') and not covered and not prior
    output(build=str(bool(build)).lower(), tag=target)
    if not build:
        emit(prior['status'] if prior else 'NO_UPDATE', key,
             'Blocked identical scheduled attempt; manual dispatch retries' if prior else 'No new eligible core; no assets downloaded', blocked=bool(prior))
        return
    dest = Path('xray-work'); dest.mkdir(exist_ok=True)
    download_verified(release, dest)
    baseline = dest / 'baseline'; baseline.mkdir(exist_ok=True)
    baseline_release = api(f'repos/{UPSTREAM}/releases/tags/{POLICY["reality_baseline"]}')
    download_verified(baseline_release, baseline, POLICY['baseline_assets'])
    manifest = dict(schema=1, kind='xray-core', architecture='linux-amd64', release_tag=target,
                    tag=release['tag_name'], upstream=UPSTREAM, upstream_prerelease=release['prerelease'],
                    published_at=release['published_at'], official_url=release['html_url'],
                    official_archive_sha256=sha(dest / 'Xray-linux-64.zip'),
                    xray_sha256=sha(dest / 'xray'), maintenance_commit=os.environ['GITHUB_SHA'],
                    run_url=(f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
                             if os.environ.get('GITHUB_ACTIONS') == 'true' else 'local validation; unpublished'),
                    minimum_candidate_version=POLICY['minimum_candidate_version'],
                    baseline=POLICY['reality_baseline'], baseline_xray_sha256=sha(baseline / 'xray'),
                    baseline_archive_sha256=sha(baseline / 'Xray-linux-64.zip'),
                    source_url=f'https://github.com/{UPSTREAM}/tree/{release["tag_name"]}')
    dist = Path('xray-dist'); dist.mkdir(exist_ok=True)
    (dist / 'xray-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    with tarfile.open(dist / ASSET, 'w:gz') as t:
        t.add(dest / 'xray', arcname='xray-linux-amd64')
        t.add(dest / 'LICENSE', arcname='LICENSE')
        t.add(dist / 'xray-manifest.json', arcname='xray-manifest.json')
    # Workflow creates validation/checksums only AFTER real traffic tests pass.
    print(json.dumps(manifest, indent=2))

if __name__ == '__main__': main()
