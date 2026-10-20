#!/usr/bin/env python3
"""Fail-closed, content-addressed sponsor patch. No fuzzy patching."""
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
FILES = [
    'internal/web/service/panel/sponsor.go',
    'internal/web/service/panel/sponsor_test.go',
    'frontend/src/api/queries/useSponsorsQuery.ts',
    'frontend/src/components/sponsor/SponsorSlot.tsx',
    'frontend/src/pages/sponsors/SponsorsPage.tsx',
    'frontend/src/layouts/AppSidebar.tsx',
]

def read(p):
    return p.read_text(encoding='utf-8').replace('\r\n', '\n')

def digest(s):
    return hashlib.sha256(s.encode()).hexdigest()

def inventory(root):
    # New sponsor entry points require a new review, even if old files match.
    found = []
    for base in ('frontend/src', 'internal'):
        for p in (root / base).rglob('*'):
            if p.suffix not in ('.go', '.ts', '.tsx') or p.name.endswith('_test.go'):
                continue
            if 'sponsor' in read(p).lower():
                found.append(p.relative_to(root).as_posix())
    return sorted(found)

def once(s, before, after):
    if s.count(before) != 1:
        raise ValueError('Expected exactly one patch anchor: ' + before[:100])
    return s.replace(before, after)

def apply(root):
    root = Path(root).resolve()
    profiles = json.loads((HERE / 'profiles.json').read_text())
    original = {f: read(root / f) for f in FILES}
    hashes = {f: digest(s) for f, s in original.items()}
    matching = [p for p in profiles if p['files'] == hashes and p['inventory'] == inventory(root)]
    if not matching:
        raise ValueError('Unknown sponsor source fingerprint. Review upstream changes; no files changed.')
    out = dict(original)
    f = FILES[0]
    out[f] = once(out[f], 'func (s *PanelService) GetSponsors()', 'func (s *PanelService) getSponsorsUpstream()')
    out[f] = once(out[f], 'func (s *PanelService) GetSponsorLogo(', 'func (s *PanelService) getSponsorLogoUpstream(')
    out[f] = once(out[f], 'sponsors, err := s.GetSponsors()', 'sponsors, err := s.getSponsorsUpstream()')
    out[f] += '''
// Local no-sponsor policy. The original implementation remains private for
// regression testing; public routes cannot reach it.
func (s *PanelService) GetSponsors() (*SponsorList, error) {
    return &SponsorList{Sponsors: []Sponsor{}}, nil
}
func (s *PanelService) GetSponsorLogo(name string) ([]byte, string, error) {
    return nil, "", ErrSponsorLogoUnknown
}
'''
    # Retain upstream regression tests against the now-private implementation.
    # New tests below exercise the actual public policy and zero network calls.
    out[FILES[1]] = out[FILES[1]].replace('.GetSponsors()', '.getSponsorsUpstream()').replace('.GetSponsorLogo(', '.getSponsorLogoUpstream(')
    out[FILES[2]] = '''import type { SponsorList } from '@/generated/types';
const EMPTY: SponsorList = { sponsors: [] };
export function useSponsorsQuery() {
  return { data: EMPTY, fetched: true };
}
'''
    out[FILES[3]] = '''// Keep all existing JSX call sites type-compatible; render no placement.
export default function SponsorSlot(_props: Record<string, unknown>) {
  return null;
}
'''
    out[FILES[4]] = '''// The old route may remain bookmarked; render no sponsor solicitation.
export default function SponsorsPage() { return null; }
'''
    out[FILES[5]] = once(out[FILES[5]], "      { key: '/sponsors', icon: 'sponsors', title: t('menu.sponsors') },\n", '')
    for f, content in out.items():
        (root / f).write_text(content, encoding='utf-8', newline='\n')
    test = '''package panel
import (
    "encoding/json"
    "errors"
    "testing"
)
func TestNoSponsorPublicPolicy(t *testing.T) {
    hits := setupSponsorServer(t, `{"sponsors":[{"id":"paid","slots":["page"],"until":"2099-01-01T00:00:00Z","link":"https://a.example/"}]}`)
    for _, debug := range []string{"false", "true"} {
        t.Setenv("XUI_DEBUG", debug)
        svc := &PanelService{}
        list, err := svc.GetSponsors()
        if err != nil { t.Fatal(err) }
        b, err := json.Marshal(list)
        if err != nil || string(b) != `{"sponsors":[]}` { t.Fatalf("unexpected: %s %v", b, err) }
        for _, name := range []string{"acme.png", "../x.png", ""} {
            b, typ, err := svc.GetSponsorLogo(name)
            if len(b) != 0 || typ != "" || !errors.Is(err, ErrSponsorLogoUnknown) { t.Fatal("logo allowed") }
        }
    }
    if hits.Load() != 0 { t.Fatal("sponsor policy performed network requests") }
}
'''
    (root / 'internal/web/service/panel/no_sponsor_test.go').write_text(test, encoding='utf-8', newline='\n')
    frontend_test = '''import { expect, test, vi } from 'vitest';
import { render } from '@testing-library/react';
import SponsorSlot from '@/components/sponsor/SponsorSlot';
import SponsorsPage from '@/pages/sponsors/SponsorsPage';
import { useSponsorsQuery } from '@/api/queries/useSponsorsQuery';
test('placements and the old sponsor page render nothing and perform no fetch', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch');
  try {
    const result = render(<><SponsorSlot slot="login" /><SponsorSlot slot="dashboard" /><SponsorsPage /></>);
    expect(result.container.innerHTML).toBe('');
    expect(useSponsorsQuery()).toEqual({ data: { sponsors: [] }, fetched: true });
    expect(fetcher).not.toHaveBeenCalled();
  } finally { fetcher.mockRestore(); }
});
'''
    (root / 'frontend/src/test/no-sponsor.test.tsx').write_text(frontend_test, encoding='utf-8', newline='\n')
    report = {'profiles': [p['version'] for p in matching], 'before': hashes,
              'after': {f: digest(s) for f, s in out.items()}}
    (root / 'no-sponsor-patch-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report

if __name__ == '__main__':
    print(json.dumps(apply(sys.argv[1]), indent=2))
