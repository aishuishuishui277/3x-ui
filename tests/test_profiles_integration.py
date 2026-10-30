"""Opt-in real upstream sources, never a live installation.
Set XUI_INTEGRATION_SOURCES to OS-path-separated reviewed Git checkouts.
"""
import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('reviewed_patch',ROOT/'maintenance/patch.py')
P=importlib.util.module_from_spec(spec); spec.loader.exec_module(P)

@unittest.skipUnless(os.environ.get('XUI_INTEGRATION_SOURCES'),'Requires reviewed upstream Git checkouts; not a synthetic source test')
class ReviewedProfilesTests(unittest.TestCase):
    def cases(self, operation):
        for source in os.environ['XUI_INTEGRATION_SOURCES'].split(os.pathsep):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                d=Path(tmp)/'upstream'
                subprocess.run(['git','-c','safe.directory=*','clone','--quiet','--no-hardlinks',source,str(d)],check=True)
                operation(d)
    def test_real_profile_and_preserved_donate(self):
        def check(d):
            sidebar=d/'frontend/src/layouts/AppSidebar.tsx'; before=P.read(sidebar)
            result=P.apply(d)
            if 'v3.11.0' in result['profiles']:
                self.assertEqual(before,P.read(sidebar))
                self.assertIn('function DonateButton',P.read(sidebar))
                self.assertIn('https://donate.sanaei.dev/',P.read(sidebar))
                registry=P.read(d/'frontend/src/routes/panelRoutes.tsx')
                self.assertNotIn("path: '/sponsors'",registry)
                self.assertIn('<Navigate to="/" replace />',P.read(d/'frontend/src/routes.tsx'))
            self.assertNotRegex(P.read(d/'frontend/src/api/queries/useSponsorsQuery.ts'),r'\b(?:fetch|HttpUtil|useQuery)\s*[.(]')
        self.cases(check)
    def test_unrelated_ui_change_allowed(self):
        def check(d):
            sidebar=d/'frontend/src/layouts/AppSidebar.tsx'
            sidebar.write_text(P.read(sidebar)+'\n// Harmless layout maintenance note.\n',encoding='utf-8')
            P.apply(d)
            self.assertIn('Harmless layout maintenance note.',P.read(sidebar))
        self.cases(check)
    def test_new_sponsor_in_existing_file_rejected_without_source_mutation(self):
        def check(d):
            target=d/'frontend/src/pages/index/IndexPage.tsx'
            target.write_text(P.read(target)+'\nconst extraAd = <SponsorSlot slot="dashboard" />;\n',encoding='utf-8')
            before=P.read(target)
            with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'): P.apply(d)
            self.assertEqual(before,P.read(target))
            self.assertFalse((d/'internal/web/service/panel/no_sponsor_test.go').exists())
        self.cases(check)
    def test_new_entry_file_rejected(self):
        def check(d):
            target=d/'frontend/src/new-paid-placement.tsx'; target.write_text('export {default} from "./components/sponsor/SponsorCard";')
            before=P.read(d/P.FILES[0])
            with self.assertRaisesRegex(ValueError,'REVIEW_REQUIRED'): P.apply(d)
            self.assertEqual(before,P.read(d/P.FILES[0]))
        self.cases(check)
    def test_unknown_commit_never_reuses_matching_profile(self):
        def check(d):
            subprocess.run(['git','-C',str(d),'-c','user.name=Local Validation','-c','user.email=local@example.invalid',
                'commit','--quiet','--allow-empty','-m','Unreviewed next version'],check=True)
            with self.assertRaisesRegex(ValueError,'Unknown source commit'): P.apply(d)
        self.cases(check)

if __name__=='__main__': unittest.main()
