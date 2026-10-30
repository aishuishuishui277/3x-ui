"""Check exact release roster, all digests, embedded manifests and test receipts.
Optional REST metadata additionally checks uploaded assets before publishing a draft.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def validate(kind, directory, remote=None):
    d = Path(directory)
    panel = kind == 'panel'
    checksum = 'SHA256SUMS' if panel else 'XRAY-SHA256SUMS'
    names = ({'x-ui-panel-linux-amd64.tar.gz','source-patched.tar.gz','manifest.json','patch-report.json','validation.json'} if panel else
             {'xray-linux-amd64.tar.gz','xray-manifest.json','xray-validation.json'})
    sums = {}
    for line in (d / checksum).read_text().splitlines():
        digest, name = line.split()
        if name in sums: raise ValueError('Duplicate release checksum')
        sums[name] = digest
    if set(sums) != names: raise ValueError('Release roster mismatch')
    for name, digest in sums.items():
        if hashlib.sha256((d / name).read_bytes()).hexdigest() != digest: raise ValueError('Release SHA256 mismatch: ' + name)
    manifest = json.loads((d / ('manifest.json' if panel else 'xray-manifest.json')).read_text())
    report = json.loads((d / ('validation.json' if panel else 'xray-validation.json')).read_text())
    path = ROOT / 'server' / ('xui-maintain.py' if panel else 'xray-maintain.py')
    spec = importlib.util.spec_from_file_location('release_validator', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    if panel:
        module.validate_package(d, manifest['release_tag'])
        required = ['go_tests','frontend_typecheck','frontend_build','frontend_unit_and_components','static_amd64',
                    'isolated_login_http','empty_sponsor_api','logo_404']
        if any(report.get(k) != 'passed' for k in required): raise ValueError('Panel validation incomplete')
        if manifest['release_tag'].split('-ns')[0] != manifest['tag']: raise ValueError('Panel release tag mismatch')
    else:
        module.validate(d, manifest['release_tag'])
        if report['baseline_client'] != manifest['baseline'] or report['baseline_xray_sha256'] != manifest['baseline_xray_sha256']:
            raise ValueError('REALITY report/manifest baseline mismatch')
        if not all('passed' in entry for entry in report['reality_vision_loopback']): raise ValueError('REALITY transfer did not pass')
    if remote:
        metadata = json.loads(Path(remote).read_text())
        if metadata['tag_name'] != manifest['release_tag']: raise ValueError('Remote tag mismatch')
        assets = metadata['assets']
        if {a['name'] for a in assets} != names | {checksum} or len(assets) != len(names) + 1:
            raise ValueError('Remote asset roster mismatch')
        for asset in assets:
            digest = hashlib.sha256((d / asset['name']).read_bytes()).hexdigest()
            if asset.get('digest') != 'sha256:' + digest: raise ValueError('Remote asset SHA256 mismatch')
    return manifest

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('kind', choices=['panel','core']); p.add_argument('directory'); p.add_argument('--remote-json')
    args = p.parse_args()
    print(json.dumps(validate(args.kind, args.directory, args.remote_json), indent=2))
