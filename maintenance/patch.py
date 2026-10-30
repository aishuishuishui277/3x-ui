#!/usr/bin/env python3
"""Fail-closed, content-addressed sponsor patch. No fuzzy patching."""
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess

HERE = Path(__file__).resolve().parent
class ReviewRequired(ValueError):
    """Reviewed source assumptions changed; distinct from a broken tool."""
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

def translation_state(root):
    return {p.relative_to(root).as_posix(): digest(json.dumps(json.loads(read(p))['pages']['sponsors'],
                ensure_ascii=False, sort_keys=True))
            for p in sorted((root / 'internal/web/translation').glob('*.json'))}

def inventory(root):
    # New sponsor entry points require a new review, even if old files match.
    found = []
    for base in ('frontend/src', 'internal'):
        for p in (root / base).rglob('*'):
            if p.suffix not in ('.go', '.ts', '.tsx', '.js', '.jsx', '.mjs', '.html') or p.name.endswith('_test.go'):
                continue
            if 'sponsor' in read(p).lower():
                found.append(p.relative_to(root).as_posix())
    return sorted(found)

def surface(root):
    # Scope UI fingerprints to paid-sponsor references, not unrelated layout.
    # A version still needs its exact reviewed commit before this can be used.
    return {f: digest('\n'.join(line.strip() for line in read(root / f).splitlines()
                if re.search('sponsor', line, re.I))) for f in inventory(root)}

def review(root, profile):
    files = profile.get('files', {})
    actual = {f: digest(read(root / f)) if (root / f).is_file() else None for f in files}
    actual_surface = surface(root)
    return {'profile': profile.get('version'),
            'changed_critical_files': [f for f in files if actual[f] != files[f]],
            'added_entries': sorted(set(inventory(root)) - set(profile['inventory'])),
            'removed_entries': sorted(set(profile['inventory']) - set(inventory(root))),
            'changed_sponsor_interfaces': [f for f in set(actual_surface) | set(profile.get('surface', {}))
                if actual_surface.get(f) != profile.get('surface', {}).get(f)],
            'translations_changed': translation_state(root) != profile['translations']}

def once(s, before, after):
    if s.count(before) != 1:
        raise ReviewRequired('Expected exactly one patch anchor: ' + before[:100])
    return s.replace(before, after)

def apply(root):
    root = Path(root).resolve()
    profiles = json.loads((HERE / 'profiles.json').read_text())
    try:
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        raise ReviewRequired('Unknown source commit; REVIEW_REQUIRED; no files changed') from None
    matching = [p for p in profiles if p['commit'] == commit]
    if not matching:
        raise ReviewRequired('Unknown source commit; REVIEW_REQUIRED; no files changed')
    profile = matching[0]
    files = list(profile['files'])
    original = {f: read(root / f) for f in files}
    hashes = {f: digest(s) for f, s in original.items()}
    translations = translation_state(root)
    report = review(root, profile)
    if hashes != profile['files'] or profile['inventory'] != inventory(root) or profile.get('surface') != surface(root) or profile['translations'] != translations:
        (root.parent / 'review-required.json').write_text(json.dumps(report, indent=2) + '\n')
        raise ReviewRequired('Unknown sponsor source fingerprint; REVIEW_REQUIRED. See review-required.json; no source files changed.')
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
    if profile.get('layout') == 'registry':
        f = 'frontend/src/routes/panelRoutes.tsx'
        out[f] = once(read(root / f), "  { path: '/sponsors', titleKey: 'menu.sponsors', icon: CrownOutlined, component: SponsorsPage },\n", '')
        out[f] = once(out[f], '  CrownOutlined,\n', '')
        out[f] = once(out[f], "const SponsorsPage = lazy(() => import('@/pages/sponsors/SponsorsPage'));\n", '')
        f = 'frontend/src/routes.tsx'
        out[f] = once(read(root / f), "import { createBrowserRouter, type RouteObject } from 'react-router';", "import { createBrowserRouter, Navigate, type RouteObject } from 'react-router';")
        out[f] = once(out[f], '    children: PANEL_ROUTES.map((route) => {', "    // Compatibility for bookmarks: preserve PanelLayout, redirect to dashboard.\n    children: [{ path: 'sponsors', element: <Navigate to=\"/\" replace /> }, ...PANEL_ROUTES.map((route) => {")
        out[f] = once(out[f], '    }),\n', '    })],\n')
        f = 'frontend/src/components/command-palette/CommandPalette.tsx'
        out[f] = once(read(root / f), "  '/sponsors': ['sponsors', 'sponsor', 'partners'],\n", '')
        # The upstream contract must still cover every real page; separately
        # assert the one intentional compatibility redirect, never skip it.
        f = 'frontend/src/test/navigation-contract.test.tsx'
        out[f] = once(read(root / f), "import { describe, expect, it } from 'vitest';", "import { describe, expect, it } from 'vitest';\nimport { Navigate } from 'react-router';")
        out[f] = once(out[f], "    const childPaths = (routes[0].children ?? []).map((child) =>", "    const children = routes[0].children ?? [];\n    expect(children.find(child => child.path === 'sponsors')?.element).toEqual(<Navigate to=\"/\" replace />);\n    const childPaths = children.filter(child => child.path !== 'sponsors').map((child) =>")
    else:
        f = FILES[5]
        out[f] = once(read(root / f), "      { key: '/sponsors', icon: 'sponsors', title: t('menu.sponsors') },\n", '')
    # Remove the deleted page's dead strings from every locale. Keep the two
    # keys still referenced by SponsorCard's private/unrendered implementation.
    for f in translations:
        text = read(root / f)
        pattern = r'(?ms)^    "sponsors": \{\n.*?^    \}'
        blocks = list(re.finditer(pattern, text))
        if len(blocks) != 1: raise ReviewRequired('Unexpected sponsor translation block: ' + f)
        block = blocks[0]
        original_section = json.loads(block.group().split(': ', 1)[1])
        kept = {k: v for k, v in original_section.items() if k in ('tag', 'visit')}
        if set(kept) != {'tag', 'visit'}: raise ReviewRequired('Unknown translation schema: ' + f)
        replacement = '    "sponsors": ' + json.dumps(kept, ensure_ascii=False, indent=2).replace('\n', '\n    ')
        out[f] = text[:block.start()] + replacement + text[block.end():]
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
    if profile.get('layout') == 'registry':
        frontend_test += '''
import { PANEL_ROUTES, PANEL_ROUTE_PATHS } from '@/routes/panelRoutes';
test('paid sponsors are absent from shared sidebar/search/title registry; other routes remain', () => {
  expect(PANEL_ROUTE_PATHS).toEqual(['/', '/inbounds', '/clients', '/groups', '/nodes', '/hosts', '/outbound', '/routing', '/settings', '/xray', '/api-docs']);
  expect(PANEL_ROUTES.some(r => r.titleKey === 'menu.sponsors')).toBe(false);
});
'''
    (root / 'frontend/src/test/no-sponsor.test.tsx').write_text(frontend_test, encoding='utf-8', newline='\n')
    report = {'profiles': [p['version'] for p in matching], 'before': hashes, 'translation_before': translations,
              'after': {f: digest(s) for f, s in out.items()}, 'inventory_after': inventory(root)}
    allowed_after = set(profile['inventory']) | set(out) | {'frontend/src/test/no-sponsor.test.tsx'}
    if set(report['inventory_after']) - allowed_after:
        raise ReviewRequired('Unexpected post-patch sponsor entry point; REVIEW_REQUIRED')
    (root / 'no-sponsor-patch-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report

if __name__ == '__main__':
    from status import emit, identity, output
    try:
        print(json.dumps(apply(sys.argv[1]), indent=2))
        output(applied='true')
    except ReviewRequired as error:
        attempt = Path('attempt.json')
        key = json.loads(attempt.read_text())['identity'] if attempt.exists() else identity('patch')
        emit('REVIEW_REQUIRED', key, str(error))
        output(applied='false')
