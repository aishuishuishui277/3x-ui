param([switch]$Publish)
$ErrorActionPreference = 'Stop'
if (-not $Publish) {
    Write-Host 'Review README.zh-CN.md. To approve creating maintenance-no-sponsor and setting it as the default branch:'
    Write-Host '.\Publish-ToFork.ps1 -Publish'
    exit 0
}
function Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with code $LASTEXITCODE" }
}
Checked 'gh' @('auth', 'status')
$repo = 'aishuishuishui277/3x-ui'
$branch = 'maintenance-no-sponsor'
$remoteBranches = & gh api "repos/$repo/branches?per_page=100" --jq '.[].name'
if ($LASTEXITCODE -ne 0) { throw 'Cannot read repository' }
if ($remoteBranches -contains $branch) { throw 'Maintenance branch already exists; inspect it before updating.' }
$taskRoot = Join-Path $PSScriptRoot '..\..\work'
New-Item -ItemType Directory -Force -Path $taskRoot | Out-Null
$checkout = Join-Path $taskRoot ('publish-' + [guid]::NewGuid().ToString('N'))
Checked 'gh' @('repo', 'clone', $repo, $checkout, '--', '--no-checkout')
Push-Location $checkout
try {
    # New orphan branch contains tooling only. Old main and no-sponsor branch survive.
    Checked 'git' @('switch', '--orphan', $branch)
    foreach ($name in @('.github', '.gitattributes', '.gitignore', 'LICENSE', 'maintenance', 'server', 'tests', 'evidence', 'README.zh-CN.md', 'VERIFICATION.md', 'INSTALL-NOW.md', 'Publish-ToFork.ps1')) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $checkout -Recurse -Force
    }
    Checked 'git' @('add', '.')
    Checked 'git' @('commit', '-m', 'Add fail-closed no-sponsor stable AMD64 maintenance')
    Checked 'git' @('push', '-u', 'origin', $branch)
    Checked 'gh' @('repo', 'edit', $repo, '--default-branch', $branch)
    # Explicit dispatch guarantees the first build even if Actions suppressed push.
    Checked 'gh' @('workflow', 'run', 'no-sponsor.yml', '--repo', $repo, '--ref', $branch)
    Write-Host "Published. Check https://github.com/$repo/actions ; VPS unchanged."
} finally { Pop-Location }
