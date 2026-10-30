#!/usr/bin/env bash
# Local disposable workspace only. No release publication or service commands.
set -euo pipefail
tag=${1:?Use v3.10.2 or v3.11.0}
test "$(uname -s)" = Linux
test "$(uname -m)" = x86_64
for tool in git python3 node npm go gofmt musl-gcc readelf file; do command -v "$tool" >/dev/null; done
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dest=${2:-$(mktemp -d)}
mkdir -p "$dest"
test -z "$(ls -A "$dest")" || { echo 'Validation output must be empty'; exit 1; }
dest=$(CDPATH= cd -- "$dest" && pwd)
for entry in maintenance server tests .github README.zh-CN.md XRAY-UPDATE.zh-CN.md; do cp -a "$root/$entry" "$dest/"; done
cd "$dest"
git clone --depth 1 --branch "$tag" https://github.com/MHSanaei/3x-ui.git upstream
XUI_INTEGRATION_SOURCES="$dest/upstream" python3 -m unittest discover -s tests -v
python3 maintenance/patch.py upstream
test -f upstream/internal/web/service/panel/no_sponsor_test.go
cd upstream/frontend
npm ci
python3 ../../maintenance/check.py frontend_typecheck -- npm run typecheck
python3 ../../maintenance/check.py frontend_unit_and_components -- npm test -- --project unit --project components
python3 ../../maintenance/check.py frontend_build -- npm run build
cd ..
export CGO_ENABLED=1 CC=musl-gcc GOOS=linux GOARCH=amd64
gofmt -w internal/web/service/panel/sponsor.go internal/web/service/panel/no_sponsor_test.go
go mod verify
python3 ../maintenance/check.py go_tests -- go test -timeout 15m ./...
python3 ../maintenance/check.py static_amd64 -- go build -trimpath -buildvcs=false -ldflags "-w -s -linkmode external -extldflags '-static'" -o ../panel .
file ../panel
readelf -h ../panel | grep 'Advanced Micro Devices X86-64'
if readelf -l ../panel | grep -q INTERP; then exit 1; fi
test "v$(../panel -v)" = "$tag"
cd ..
python3 - "$tag" <<'PY'
import json,sys,subprocess
from pathlib import Path
tag=sys.argv[1]
sha=subprocess.check_output(['git','-C','upstream','rev-parse','HEAD'],text=True).strip()
Path('selection.json').write_text(json.dumps(dict(tag=tag,release_tag=tag+'-ns1',upstream_commit=sha,
  maintenance_commit='local-validation-unpublished',run_url='local validation; not GitHub publication')))
PY
python3 maintenance/package.py
python3 maintenance/smoke.py
python3 maintenance/verify_release.py panel dist
printf 'VALIDATED (unpublished): %s/dist\n' "$dest"
