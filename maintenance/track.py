#!/usr/bin/env python3
"""Resolve a real stable release, reject downgrades, bind tag to peeled commit."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
from status import blocked, emit, identity, output, release_identity

UPSTREAM = 'MHSanaei/3x-ui'
def api(path):
    req = urllib.request.Request('https://api.github.com/' + path, headers={
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'})
    if os.environ.get('GH_TOKEN'): req.add_header('Authorization', 'Bearer ' + os.environ['GH_TOKEN'])
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
    backwards = not requested and any(version(r['tag_name'].split('-')[0]) > version(tag) for r in published)
    found = next((r for r in published if r['tag_name'] == custom), None)
    if found:
        names = {a['name'] for a in found['assets']}
        if not {'x-ui-panel-linux-amd64.tar.gz', 'SHA256SUMS', 'manifest.json', 'source-patched.tar.gz', 'patch-report.json', 'validation.json'} <= names:
            raise ValueError('Published release incomplete; manual inspection required')
    ref = api(f'repos/{UPSTREAM}/git/ref/tags/{tag}')['object']
    while ref['type'] == 'tag': ref = api(f'repos/{UPSTREAM}/git/tags/{ref["sha"]}')['object']
    if ref['type'] != 'commit': raise ValueError('Tag does not resolve to a commit')
    sha = ref['sha']
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Invalid upstream commit')
    profiles = json.loads((Path(__file__).parent / 'profiles.json').read_text())
    profile = next((p for p in profiles if p['version'] == tag and p['commit'] == sha), None)
    key = identity('panel', sha, release_identity(release))
    Path('attempt.json').write_text(json.dumps({'identity':key}) + '\n')
    prior = blocked(key)
    output(tag=tag, release_tag=custom, build='false')
    if backwards:
        emit('REVIEW_REQUIRED', key, 'Upstream latest moved backwards; no downgrade/build')
        return
    if prior:
        emit(prior['status'], key, 'Identical blocked scheduled attempt; manual dispatch/code change retries', blocked=True)
        return
    if not profile:
        previous = next((p for p in profiles if p['version'] == tag), profiles[-1])
        report = dict(status='REVIEW_REQUIRED', tag=tag, actual_commit=sha,
                      reviewed_commit=previous['commit'], tag_moved=previous['version']==tag,
                      compare_url=f'https://github.com/{UPSTREAM}/compare/{previous["commit"]}...{sha}')
        comparison = api(f'repos/{UPSTREAM}/compare/{previous["commit"]}...{sha}')
        report['changed_files'] = [f['filename'] for f in comparison.get('files', [])]
        report['sponsor_related_changes'] = [f['filename'] for f in comparison.get('files', [])
            if 'sponsor' in (f['filename'] + f.get('patch','')).lower()]
        Path('review-required.json').write_text(json.dumps(report, indent=2) + '\n')
        emit('REVIEW_REQUIRED', key, 'Unreviewed source; no patch/build/publication. See review-required.json', report=report)
        return
    if found and os.environ.get('FORCE_VALIDATE') != 'true':
        emit('NO_UPDATE', key, 'Complete reviewed release already published; no clone/build/download')
        return
    subprocess.run(['git', 'clone', '--depth', '1', '--branch', tag, f'https://github.com/{UPSTREAM}.git', 'upstream'], check=True)
    actual = subprocess.check_output(['git','-C','upstream','rev-parse','HEAD'], text=True).strip()
    if actual != sha: raise ValueError('Upstream tag changed during checkout')
    data = dict(tag=tag, release_tag=custom, upstream_commit=sha, upstream_published_at=release['published_at'],
                maintenance_commit=os.environ['GITHUB_SHA'], patch_revision=revision,
                run_url=(f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
                         if os.environ.get('GITHUB_ACTIONS') == 'true' else 'local validation; unpublished'))
    Path('selection.json').write_text(json.dumps(data, indent=2) + '\n')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
        for k, v in dict(build='true', tag=tag, release_tag=custom).items():
            f.write(f'{k}={v}\n')
    print(json.dumps(data, indent=2))

if __name__ == '__main__':
    main()
