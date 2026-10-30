#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
from xray_release import api, download_asset

def sha(p):
    with open(p, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def main():
    selected = json.loads(Path('selection.json').read_text())
    tag = selected['tag']
    profile = next(p for p in json.loads(Path('maintenance/profiles.json').read_text())
                   if p['version'] == tag and p['commit'] == selected['upstream_commit'])
    dist = Path('dist'); dist.mkdir(exist_ok=True)
    # Reuse the matching official release's Xray, not moving 'latest' downloads.
    official = Path('official'); official.mkdir(exist_ok=True)
    release = api(f'repos/MHSanaei/3x-ui/releases/tags/{tag}')
    import urllib.request
    for name in ('x-ui-linux-amd64.tar.gz', 'x-ui-linux-amd64.tar.gz.sha256'):
        asset = next(a for a in release['assets'] if a['name'] == name)
        url = f'https://github.com/MHSanaei/3x-ui/releases/download/{tag}/{name}'
        if asset['browser_download_url'] != url: raise ValueError('Unexpected official panel asset URL')
        download_asset(url, official / name, asset.get('digest'))
        if asset.get('digest') != 'sha256:' + sha(official / name):
            raise ValueError('Official panel asset digest mismatch/missing')
    archive = official / 'x-ui-linux-amd64.tar.gz'
    expected = (official / (archive.name + '.sha256')).read_text().split()[0]
    if sha(archive) != expected or expected != profile['bundle']['official_archive_sha256']:
        raise ValueError('Official release SHA256 mismatch')
    payload = Path('payload'); payload.mkdir(exist_ok=True)
    shutil.copy2('panel', payload / 'x-ui')
    (payload / 'x-ui').chmod(0o755)
    (payload / 'bin').mkdir(exist_ok=True)
    with tarfile.open(archive) as t:
        entry = t.getmember('x-ui/bin/xray-linux-amd64')
        if not entry.isfile() or entry.size > 200_000_000:
            raise ValueError('Unexpected Xray archive member')
        with t.extractfile(entry) as f:
            (payload / 'bin/xray-linux-amd64').write_bytes(f.read())
    core = payload / 'bin/xray-linux-amd64'; core.chmod(0o755)
    version = subprocess.check_output([str(core.resolve()), 'version'], text=True).splitlines()[0]
    if not version.startswith('Xray ' + profile['bundle']['xray_version'] + ' ') or sha(core) != profile['bundle']['xray_sha256']:
        raise ValueError('Bundled core changed; explicit review of new Xray required: ' + version)
    manifest = dict(selected, schema=1, architecture='linux-amd64', panel_sha256=sha(payload / 'x-ui'),
                    xray_sha256=sha(core), xray_version=profile['bundle']['xray_version'], official_archive_sha256=expected,
                    license='GPL-3.0', source_asset='source-patched.tar.gz')
    (dist / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copy2(dist / 'manifest.json', payload / 'manifest.json')
    shutil.copy2('upstream/LICENSE', payload / 'LICENSE')
    report_path = Path('upstream/no-sponsor-patch-report.json')
    report = json.loads(report_path.read_text())
    report['after_gofmt'] = {f: sha(Path('upstream') / f) for f in report['after']}
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    shutil.copy2(report_path, dist / 'patch-report.json')
    with tarfile.open(dist / 'x-ui-panel-linux-amd64.tar.gz', 'w:gz') as t:
        t.add(payload, arcname='x-ui')
    def source_filter(info):
        if any(x in ('.git', 'node_modules', '__pycache__') for x in Path(info.name).parts):
            return None
        return info
    with tarfile.open(dist / 'source-patched.tar.gz', 'w:gz') as t:
        t.add('upstream', arcname='source', filter=source_filter)
        t.add('maintenance', arcname='maintenance', filter=source_filter)
        t.add('server', arcname='server', filter=source_filter)
        t.add('tests', arcname='tests', filter=source_filter)
        t.add('.github/workflows/no-sponsor.yml', arcname='maintenance-workflow.yml')
        t.add('.github/workflows/xray.yml', arcname='xray-maintenance-workflow.yml')
        t.add('README.zh-CN.md', arcname='README.zh-CN.md')
        t.add('XRAY-UPDATE.zh-CN.md', arcname='XRAY-UPDATE.zh-CN.md')
    (dist / 'RELEASE-NOTES.md').write_text(f'''自动去赞助构建 {selected['release_tag']}

上游正式标签: {tag}
上游提交: {selected['upstream_commit']}
维护提交: {selected['maintenance_commit']}
测试与构建日志: {selected['run_url']}
面板包仅用于现有安装；默认保留服务器现有 Xray、Geo 文件、systemd 和数据库。
可选附带 Xray: {version}
完整修改源码、GPL 许可证、补丁指纹、校验报告随附。
通过构建及隔离 HTTP 测试不代表已通过用户 Reality 节点的远端端到端测试。
''', encoding='utf-8')

if __name__ == '__main__':
    main()
