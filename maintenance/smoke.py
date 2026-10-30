#!/usr/bin/env python3
"""Never use the host /etc/x-ui; smoke-test isolated SQLite and a free port."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for folder in ('db', 'logs', 'bin'):
            (base / folder).mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        env = dict(os.environ, XUI_DB_FOLDER=str(base / 'db'), XUI_LOG_FOLDER=str(base / 'logs'),
                   XUI_BIN_FOLDER=str(base / 'bin'), XUI_PORT=str(port), XUI_INIT_WEB_BASE_PATH='/smoke/')
        with open(base / 'panel.log', 'wb') as log:
            p = subprocess.Popen([str(Path('panel').resolve())], env=env, cwd=base, stdout=log, stderr=log)
            try:
                url = f'http://127.0.0.1:{port}/smoke/'
                for _ in range(90):
                    if p.poll() is not None:
                        raise RuntimeError('Panel exited: ' + (base / 'panel.log').read_text())
                    try:
                        with urllib.request.urlopen(url, timeout=2) as r:
                            if r.status != 200 or b'<html' not in r.read().lower():
                                raise ValueError('Login HTML/status mismatch')
                        break
                    except OSError:
                        time.sleep(1)
                else:
                    raise RuntimeError('Panel readiness timeout')
                with urllib.request.urlopen(url + 'sponsors', timeout=5) as r:
                    data = json.load(r)
                    if not data.get('success') or data.get('obj') != {'sponsors': []}:
                        raise ValueError('Sponsor policy mismatch: ' + str(data))
                try:
                    urllib.request.urlopen(url + 'sponsors/logo/acme.png', timeout=5)
                    raise AssertionError('Logo endpoint allowed')
                except urllib.error.HTTPError as e:
                    if e.code != 404: raise ValueError('Unexpected sponsor logo status: ' + str(e.code)) from e
            finally:
                p.terminate()
                try: p.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    p.kill(); p.wait()
    dist = Path('dist')
    evidence = {p.stem:json.loads(p.read_text()) for p in Path('validation-evidence').glob('*.json')}
    required = ['go_tests','frontend_typecheck','frontend_build','frontend_unit_and_components','static_amd64']
    if any(evidence.get(k, {}).get('status') != 'passed' for k in required):
        raise ValueError('Missing/failed real validation receipts; cannot mark build as passed')
    report = {k:evidence[k]['status'] for k in required}
    report.update(isolated_login_http='passed',empty_sponsor_api='passed',logo_404='passed',live_reality='not tested')
    (dist / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    names = ['x-ui-panel-linux-amd64.tar.gz', 'source-patched.tar.gz', 'manifest.json', 'patch-report.json', 'validation.json']
    (dist / 'SHA256SUMS').write_text(''.join(hashlib.sha256((dist / n).read_bytes()).hexdigest() + '  ' + n + '\n' for n in names))

if __name__ == '__main__':
    main()
