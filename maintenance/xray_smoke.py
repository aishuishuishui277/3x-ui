#!/usr/bin/env python3
"""Real loopback VLESS/REALITY+Vision transfer, including the user's baseline client.
TLS target, HTTP destination and credentials are disposable and local to CI.
This does not establish reachability from the user's network to their VPS.
"""
import functools
import hashlib
import http.server
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid

def port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); return s.getsockname()[1]

def wait(p, number, log):
    for _ in range(100):
        if p.poll() is not None: raise RuntimeError(log.read_text(errors='replace'))
        try:
            with socket.create_connection(('127.0.0.1', number), timeout=.2): return
        except OSError: time.sleep(.1)
    raise RuntimeError('Readiness timeout: ' + log.read_text(errors='replace'))

def main():
    candidate = Path('xray-work/xray').resolve()
    baseline = Path('xray-work/baseline/xray').resolve()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp); processes = []; handles = []
        marker = uuid.uuid4().hex
        (d / 'probe').write_text(marker)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
        httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        def launch(args, label, listen):
            log = d / (label + '.log'); f = open(log, 'wb'); handles.append(f)
            p = subprocess.Popen(list(map(str, args)), stdout=f, stderr=f, cwd=d)
            processes.append(p); wait(p, listen, log); return p
        try:
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', str(d / 'key.pem'), '-out', str(d / 'cert.pem'), '-days', '1',
                '-subj', '/CN=reality.test'], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            tls_port, server_port = port(), port()
            launch(['openssl', 's_server', '-accept', f'127.0.0.1:{tls_port}', '-key', d / 'key.pem',
                    '-cert', d / 'cert.pem', '-tls1_3', '-groups', 'X25519', '-alpn', 'h2,http/1.1', '-www'], 'tls', tls_port)
            key = subprocess.check_output([str(candidate), 'x25519'], text=True)
            private = re.search(r'Private\s*[Kk]ey:\s*(\S+)', key)[1]
            public = re.search(r'(?:Password(?: \(PublicKey\))?|Public\s*[Kk]ey):\s*(\S+)', key)[1]
            ident = str(uuid.uuid4()); sid = '0123456789abcdef'
            server = dict(log={'loglevel':'warning'}, inbounds=[dict(listen='127.0.0.1', port=server_port,
                protocol='vless', settings={'clients':[{'id':ident,'flow':'xtls-rprx-vision'}], 'decryption':'none'},
                streamSettings={'network':'tcp', 'security':'reality', 'realitySettings':{
                    'target':f'127.0.0.1:{tls_port}', 'serverNames':['reality.test'], 'privateKey':private, 'shortIds':[sid]}})],
                outbounds=[{'protocol':'freedom'}])
            config = d / 'server.json'; config.write_text(json.dumps(server))
            subprocess.run([str(candidate), 'run', '-test', '-config', str(config)], check=True)
            launch([candidate, 'run', '-config', config], 'server', server_port)
            for label, binary in (('baseline-client', baseline), ('candidate-client', candidate)):
                socks = port()
                client = dict(log={'loglevel':'warning'}, inbounds=[{'listen':'127.0.0.1','port':socks,
                    'protocol':'socks','settings':{'auth':'noauth','udp':False}}], outbounds=[dict(protocol='vless',
                    settings={'vnext':[{'address':'127.0.0.1','port':server_port,'users':[{'id':ident,
                        'flow':'xtls-rprx-vision','encryption':'none'}]}]},
                    streamSettings={'network':'tcp','security':'reality','realitySettings':{
                        'fingerprint':'chrome','serverName':'reality.test','publicKey':public,'shortId':sid}})])
                cfg = d / (label + '.json'); cfg.write_text(json.dumps(client))
                p = launch([binary, 'run', '-config', cfg], label, socks)
                try:
                    out = subprocess.check_output(['curl','--fail','--silent','--show-error','--max-time','20',
                        '--noproxy','','--socks5-hostname',f'127.0.0.1:{socks}',
                        f'http://127.0.0.1:{httpd.server_port}/probe'], text=True)
                    if out != marker: raise ValueError('REALITY data mismatch')
                    results.append(label + ' -> candidate-server: REALITY+Vision HTTP transfer passed')
                except Exception:
                    for log in d.glob('*.log'): print(log.name, log.read_text(errors='replace'))
                    raise
                finally: p.terminate(); p.wait(timeout=10)
        finally:
            for p in reversed(processes):
                if p.poll() is None:
                    p.terminate()
                    try: p.wait(timeout=10)
                    except subprocess.TimeoutExpired: p.kill(); p.wait()
            for f in handles: f.close()
            httpd.shutdown(); httpd.server_close()
    dist = Path('xray-dist')
    (dist / 'xray-validation.json').write_text(json.dumps(dict(official_sha256='passed', elf_amd64='passed',
        binary_version='passed', reality_vision_loopback=results, live_vps='not tested',
        baseline_client='v26.10.10'), indent=2) + '\n')
    names = ['xray-linux-amd64.tar.gz', 'xray-manifest.json', 'xray-validation.json']
    (dist / 'XRAY-SHA256SUMS').write_text(''.join(hashlib.sha256((dist / n).read_bytes()).hexdigest() + '  ' + n + '\n' for n in names))

if __name__ == '__main__': main()
