import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'maintenance'))
import verify_release as V
import test_maintenance as fixtures
M=fixtures.M

class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.d=Path(self.tmp.name)
        f=fixtures.SafetyTests(); f.d=self.d; self.tag=f.package()
        (self.d/'source-patched.tar.gz').write_bytes(b'fixture source')
        (self.d/'patch-report.json').write_text('{}')
        keys=('go_tests','frontend_typecheck','frontend_build','frontend_unit_and_components','static_amd64',
              'isolated_login_http','empty_sponsor_api','logo_404')
        (self.d/'validation.json').write_text(json.dumps(dict.fromkeys(keys,'passed')))
        self.sums()
    def tearDown(self): self.tmp.cleanup()
    def sums(self):
        names=(M.ASSET,'source-patched.tar.gz','manifest.json','patch-report.json','validation.json')
        (self.d/'SHA256SUMS').write_text(''.join(M.sha(self.d/n)+'  '+n+'\n' for n in names))
    def test_complete_checked_panel_accepted(self):
        self.assertEqual(V.validate('panel',self.d)['release_tag'],self.tag)
    def test_unrun_or_failed_test_never_reaches_publication_gate(self):
        obj=json.loads((self.d/'validation.json').read_text())
        for status in ('not run','failed','running'):
            obj['go_tests']=status; (self.d/'validation.json').write_text(json.dumps(obj)); self.sums()
            with self.assertRaisesRegex(ValueError,'validation incomplete'): V.validate('panel',self.d)
    def test_incomplete_roster_rejected(self):
        p=self.d/'SHA256SUMS'; p.write_text('\n'.join(p.read_text().splitlines()[:-1]))
        with self.assertRaisesRegex(ValueError,'roster mismatch'): V.validate('panel',self.d)
    def test_remote_metadata_requires_exact_digests_and_tag(self):
        names=(M.ASSET,'source-patched.tar.gz','manifest.json','patch-report.json','validation.json','SHA256SUMS')
        obj={'tag_name':self.tag,'assets':[dict(name=n,digest='sha256:'+M.sha(self.d/n)) for n in names]}
        remote=self.d/'remote.json'; remote.write_text(json.dumps(obj)); V.validate('panel',self.d,remote)
        obj['assets'][0]['digest']='sha256:'+'f'*64; remote.write_text(json.dumps(obj))
        with self.assertRaisesRegex(ValueError,'Remote asset SHA256'): V.validate('panel',self.d,remote)
    def test_workflows_require_success_and_explicit_publish_scope(self):
        for name in ('no-sponsor.yml','xray.yml'):
            text=(ROOT/'.github/workflows'/name).read_text(encoding='utf-8')
            self.assertNotIn('continue-on-error',text)
            self.assertIn("github.ref_name == 'maintenance-no-sponsor'",text)
            self.assertIn('inputs.publish == true',text)
            self.assertIn('needs:',text)

if __name__=='__main__': unittest.main()
