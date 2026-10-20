#!/usr/bin/env python3
"""Resolve a real stable release, reject downgrades, bind tag to peeled commit."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

UPSTREAM = 'MHSanaei/3x-ui'
def api(path):
    req = urllib.request.Request('https://api.github.com/' + path, headers={
        'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def version(tag):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Only plain stable vX.Y.Z tags supported')
    return tuple(map(int, tag[1:].split('.')))

def main():
    requested = os.environ.get('REQUESTED_TAG', '').strip()
    release = api(f'repos/{UPSTREAM}/releases/' + ('tags/' + requested if requested else 'latest'))
    tag = release['tag_name']
    if release['draft'] or release['prerelease'] or version(tag) < version('v3.10.0'):
        raise ValueError('Not a supported stable release')
    # Include draft tags: an interrupted publication is retried rather than skipped.
    existing = api(f"repos/{os.environ['GITHUB_REPOSITORY']}/releases?per_page=100")
    revision = 'ns1'
    custom = tag + '-' + revision
    published = [r for r in existing if re.fullmatch(r'v\d+\.\d+\.\d+-ns\d+', r['tag_name']) and not r['draft']]
    if not requested and any(version(r['tag_name'].split('-')[0]) > version(tag) for r in published):
        raise ValueError('Upstream latest moved backwards; refusing automatic downgrade')
    found = next((r for r in published if r['tag_name'] == custom), None)
    if found:
        names = {a['name'] for a in found['assets']}
        if not {'x-ui-panel-linux-amd64.tar.gz', 'SHA256SUMS', 'manifest.json', 'source-patched.tar.gz'} <= names:
            raise ValueError('Published release incomplete; manual inspection required')
    run = 'false' if found else 'true'
    subprocess.run(['git', 'clone', '--depth', '1', '--branch', tag, f'https://github.com/{UPSTREAM}.git', 'upstream'], check=True)
    sha = subprocess.check_output(['git', '-C', 'upstream', 'rev-parse', 'HEAD'], text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Invalid upstream commit')
    profiles = json.loads((Path(__file__).parent / 'profiles.json').read_text())
    for profile in profiles:
        if profile['version'] == tag and profile['commit'] != sha:
            raise ValueError('Previously reviewed upstream tag has moved; review required')
    data = dict(tag=tag, release_tag=custom, upstream_commit=sha, upstream_published_at=release['published_at'],
                maintenance_commit=os.environ['GITHUB_SHA'], patch_revision=revision,
                run_url=f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    Path('selection.json').write_text(json.dumps(data, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        for k, v in dict(build=run, tag=tag, release_tag=custom).items():
            f.write(f'{k}={v}\n')
    print(json.dumps(data, indent=2))

if __name__ == '__main__':
    main()
