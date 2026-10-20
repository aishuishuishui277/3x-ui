#!/usr/bin/env python3
"""Monthly maintenance check record keeps an otherwise idle public fork active."""
import datetime
import json
from pathlib import Path
import subprocess

def main():
    path = Path('maintenance/last-scheduled-check.json')
    now = datetime.datetime.now(datetime.timezone.utc)
    if path.exists():
        previous = datetime.datetime.fromisoformat(json.loads(path.read_text())['checked_at'])
        if (now - previous).days < 28: return
    path.write_text(json.dumps({'checked_at': now.isoformat(), 'purpose': 'scheduled maintenance activity record'}, indent=2) + '\n')
    for args in (['git', 'config', 'user.name', 'github-actions[bot]'],
                 ['git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com'],
                 ['git', 'add', str(path)], ['git', 'commit', '-m', 'Record scheduled maintenance check'], ['git', 'push']):
        subprocess.run(args, check=True)

if __name__ == '__main__': main()
