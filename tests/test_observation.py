import contextlib
import copy
import importlib.util
import json
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'maintenance'))
import status as S
import track as T
import xray_release as X

@contextlib.contextmanager
def workspace():
    old = Path.cwd()
    with tempfile.TemporaryDirectory() as d:
        os.chdir(d)
        with patch.dict(os.environ, dict(GITHUB_REPOSITORY='aishuishuishui277/3x-ui',
                GITHUB_OUTPUT=str(Path(d)/'outputs'), GITHUB_EVENT_NAME='schedule'), clear=False):
            try: yield Path(d)
            finally: os.chdir(old)

def core_release():
    return dict(tag_name='v26.10.29', draft=False, prerelease=False, assets=[
        dict(name='Xray-linux-64.zip',digest='sha256:'+'a'*64, download_count=1)])

class ObservationTests(unittest.TestCase):
    def test_verified_asset_cache_avoids_duplicate_download(self):
        with workspace() as d, patch.object(X.urllib.request,'urlopen') as fetch:
            p=d/'asset'; p.write_bytes(b'official')
            X.download_asset('https://example.invalid/asset',p,'sha256:'+hashlib.sha256(b'official').hexdigest())
            fetch.assert_not_called()
    def test_network_retry_does_not_bypass_digest(self):
        with workspace() as d, patch.object(X.urllib.request,'urlopen',side_effect=[OSError('TLS interruption'),io.BytesIO(b'official')]) as fetch, patch.object(X.time,'sleep'):
            p=d/'asset'; X.download_asset('https://example.invalid/asset',p,'sha256:'+hashlib.sha256(b'official').hexdigest())
            self.assertEqual(fetch.call_count,2); self.assertEqual(p.read_bytes(),b'official')
    def test_corrupted_asset_is_never_promoted_from_partial_file(self):
        with workspace() as d, patch.object(X.urllib.request,'urlopen',return_value=io.BytesIO(b'corrupt')):
            p=d/'asset'
            with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):
                X.download_asset('https://example.invalid/asset',p,'sha256:'+hashlib.sha256(b'official').hexdigest())
            self.assertFalse(p.exists()); self.assertFalse(p.with_name('asset.partial').exists())
    def test_release_identity_ignores_volatile_download_counts(self):
        r=core_release(); changed=copy.deepcopy(r); changed['assets'][0]['download_count']=999
        self.assertEqual(S.release_identity(r),S.release_identity(changed))
        changed['assets'][0]['digest']='sha256:'+'b'*64
        self.assertNotEqual(S.release_identity(r),S.release_identity(changed))
    def test_blocked_state_retries_manual_dispatch_and_code_change(self):
        with workspace():
            Path('maintenance').mkdir(); p=Path('maintenance/policy.json'); p.write_text('reviewed')
            key=S.identity('tag','sha'); S.emit('TEST_FAILED',key,'real failure')
            self.assertEqual(S.blocked(key)['status'],'TEST_FAILED')
            with patch.dict(os.environ,GITHUB_EVENT_NAME='workflow_dispatch'): self.assertIsNone(S.blocked(key))
            p.write_text('new reviewed code'); self.assertIsNone(S.blocked(S.identity('tag','sha')))
    def test_all_states_distinct_and_no_failed_state_becomes_no_update(self):
        with workspace():
            for state in ('NO_UPDATE','REVIEW_REQUIRED','BUILD_FAILED','TEST_FAILED','PUBLISHED','VALIDATED'):
                self.assertEqual(S.emit(state,'key')['status'],state)
            with self.assertRaises(ValueError): S.emit('success','key')
    def test_no_new_core_does_not_download_candidate_or_baseline(self):
        r=core_release()
        own=dict(tag_name='xray-v26.10.29-r1',draft=False,assets=[{'name':n} for n in
            (X.ASSET,'xray-manifest.json','xray-validation.json','XRAY-SHA256SUMS')])
        with workspace(), patch.dict(os.environ, CHANNEL='stable', XRAY_TAG='', FORCE_VALIDATE='false'), \
                patch.object(X,'api',side_effect=[[r],[own]]), patch.object(X,'download_verified') as download:
            X.main(); download.assert_not_called()
            self.assertEqual(json.loads(Path('maintenance-status.json').read_text())['status'],'NO_UPDATE')
    def test_identical_core_failure_blocks_but_preserves_failed_status(self):
        r=core_release()
        with workspace(), patch.dict(os.environ, CHANNEL='stable', XRAY_TAG='', FORCE_VALIDATE='false'), \
                patch.object(X,'api',side_effect=lambda path: [r] if 'XTLS' in path else []):
            key=S.identity('xray',S.release_identity(r),X.POLICY,'stable','')
            S.emit('BUILD_FAILED',key,'baseline asset unavailable')
            with patch.object(X,'download_verified') as download:
                X.main(); download.assert_not_called()
            obj=json.loads(Path('maintenance-status.json').read_text())
            self.assertEqual(obj['status'],'BUILD_FAILED'); self.assertTrue(obj['blocked'])
    def test_official_baseline_metadata_mutation_rejected_before_download(self):
        r=dict(tag_name='v26.10.21',assets=[dict(name='Xray-linux-64.zip',digest='sha256:'+'0'*64,
            browser_download_url='https://github.com/XTLS/Xray-core/releases/download/v26.10.21/Xray-linux-64.zip')])
        with workspace() as d, patch.object(X.urllib.request,'urlopen') as fetch:
            with self.assertRaisesRegex(ValueError,'baseline asset digest'): X.download_verified(r,d,X.POLICY['baseline_assets'])
            fetch.assert_not_called()
    def test_panel_no_update_does_not_clone(self):
        profiles=json.loads((ROOT/'maintenance/profiles.json').read_text())
        profile=next(p for p in profiles if p['version']=='v3.10.2')
        release=dict(tag_name='v3.10.2',draft=False,prerelease=False,assets=[])
        own=dict(tag_name='v3.10.2-ns1',draft=False,assets=[{'name':n} for n in
            ('x-ui-panel-linux-amd64.tar.gz','SHA256SUMS','manifest.json','source-patched.tar.gz','patch-report.json','validation.json')])
        def api(path):
            if '/git/ref/' in path: return {'object':{'type':'commit','sha':profile['commit']}}
            if 'MHSanaei' in path: return release
            return [own]
        with workspace(), patch.dict(os.environ,REQUESTED_TAG='',FORCE_VALIDATE='false'), \
                patch.object(T,'api',side_effect=api), patch.object(T.subprocess,'run') as clone:
            T.main(); clone.assert_not_called()
            self.assertEqual(json.loads(Path('maintenance-status.json').read_text())['status'],'NO_UPDATE')
    def test_unknown_panel_reports_review_no_build(self):
        release=dict(tag_name='v3.12.0',draft=False,prerelease=False,assets=[])
        def api(path):
            if '/git/ref/' in path: return {'object':{'type':'commit','sha':'f'*40}}
            if '/compare/' in path: return {'files':[{'filename':'frontend/src/new-sponsor.tsx','patch':'+SponsorSlot'}]}
            if 'MHSanaei' in path: return release
            return []
        with workspace(), patch.dict(os.environ,REQUESTED_TAG='',FORCE_VALIDATE='false'), \
                patch.object(T,'api',side_effect=api), patch.object(T.subprocess,'run') as clone:
            T.main(); clone.assert_not_called()
            obj=json.loads(Path('review-required.json').read_text())
            self.assertEqual(obj['status'],'REVIEW_REQUIRED')
            self.assertEqual(obj['sponsor_related_changes'],['frontend/src/new-sponsor.tsx'])
    def test_minimum_baseline_and_panel_bundles_are_separate(self):
        profiles=json.loads((ROOT/'maintenance/profiles.json').read_text())
        old=next(p for p in profiles if p['version']=='v3.10.2')
        new=next(p for p in profiles if p['version']=='v3.11.0')
        self.assertEqual(X.POLICY['reality_baseline'],'v26.10.21')
        self.assertEqual(old['bundle']['xray_version'],'26.10.10')
        self.assertEqual(new['bundle']['xray_version'],'26.10.21')
        self.assertIn('minimum_candidate_version',X.POLICY)
    def test_failed_check_receipt_is_not_passed(self):
        with workspace() as d:
            script=d/'check.py'; script.write_text((ROOT/'maintenance/check.py').read_text())
            # Script resolves ROOT to its parent.parent; place it in its own maintenance folder.
            folder=d/'case'/'maintenance'; folder.mkdir(parents=True); target=folder/'check.py'; target.write_text(script.read_text())
            run=subprocess.run([sys.executable,str(target),'failure','--',sys.executable,'-c','raise SystemExit(7)'])
            self.assertEqual(run.returncode,7)
            record=json.loads((d/'case/validation-evidence/failure.json').read_text())
            self.assertEqual(record['status'],'failed')

if __name__=='__main__': unittest.main()
