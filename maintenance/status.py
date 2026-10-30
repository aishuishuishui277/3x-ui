"""Explicit observations; only scheduled identical blocked attempts are suppressed.

Cache records are advisory: publication must still pass all current gates.
Manual dispatch and code/policy/input changes always retry.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

STATES = {'NO_UPDATE', 'REVIEW_REQUIRED', 'BUILD_FAILED', 'TEST_FAILED', 'PUBLISHED', 'VALIDATED'}

def release_identity(release):
    return {'tag': release['tag_name'], 'prerelease': release['prerelease'],
            'assets': sorted((a['name'], a.get('digest')) for a in release['assets'])}

def identity(*values):
    h = hashlib.sha256()
    for folder in ('maintenance', '.github/workflows', 'tests'):
        for p in sorted(Path(folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.name != 'last-scheduled-check.json':
                h.update(p.as_posix().encode()); h.update(p.read_bytes())
    h.update(json.dumps(values, sort_keys=True).encode())
    return h.hexdigest()

def state_path():
    return Path(os.environ.get('OBSERVATION_DIR', '.maintenance-state')) / 'observation.json'

def blocked(key):
    p = state_path()
    if os.environ.get('GITHUB_EVENT_NAME') != 'schedule' or not p.exists(): return None
    record = json.loads(p.read_text(encoding='utf-8'))
    if record.get('identity') == key and record.get('status') in {'BUILD_FAILED','TEST_FAILED','REVIEW_REQUIRED'}:
        return record
    return None

def emit(status, key, detail='', **extra):
    if status not in STATES: raise ValueError('Unknown maintenance state')
    record = dict(status=status, identity=key, detail=detail, **extra)
    p = state_path(); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    Path('maintenance-status.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
            f.write('status=' + status + '\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(f'### {status}\n\n{detail}\n\nNo VPS deployment.\n')
    print(json.dumps(record))
    return record

def output(**values):
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
            for k, v in values.items(): f.write(f'{k}={v}\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('status', choices=sorted(STATES))
    args = parser.parse_args()
    path = Path('attempt.json')
    attempt = json.loads(path.read_text()) if path.exists() else {'identity': identity('selection')}
    emit(args.status, attempt['identity'], 'Current attempt ' + args.status)
