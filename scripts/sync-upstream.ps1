# Sync upstream into the fork: fast-forward `main`, then merge into
# `personal`. See FORK.md for the branch model.
#
# Remote naming note: in this clone `origin` points at the upstream
# maintainer's repo and `fork` points at the personal fork. That is the
# inverse of the usual convention; the variables below isolate the
# difference so the script is portable.
#
# Usage:
#   .\scripts\sync-upstream.ps1
#
# Idempotent. Refuses to run with a dirty working tree.

$ErrorActionPreference = "Stop"

$UpstreamRemote = "origin"
$ForkRemote = "fork"
$MainBranch = "main"
$PersonalBranch = "personal"

function Invoke-Git {
    param([string[]]$Args)
    & git @Args
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Args -join ' ') failed (exit $LASTEXITCODE)"
    }
}

# One-time: register the `ours` merge driver so .gitattributes works.
& git config --local merge.ours.driver true | Out-Null

$dirty = & git status --porcelain
if ($dirty) {
    Write-Error "Working tree is dirty. Commit or stash before syncing."
    exit 1
}

$startBranch = (& git rev-parse --abbrev-ref HEAD).Trim()

Write-Host "[1/4] Fetching $UpstreamRemote..." -ForegroundColor Cyan
Invoke-Git @("fetch", $UpstreamRemote)

Write-Host "[2/4] Fast-forwarding $MainBranch to $UpstreamRemote/$MainBranch..." -ForegroundColor Cyan
Invoke-Git @("checkout", $MainBranch)
Invoke-Git @("merge", "--ff-only", "$UpstreamRemote/$MainBranch")
Invoke-Git @("push", $ForkRemote, $MainBranch)

Write-Host "[3/4] Merging $MainBranch into $PersonalBranch..." -ForegroundColor Cyan
Invoke-Git @("checkout", $PersonalBranch)
Invoke-Git @("merge", "--no-edit", $MainBranch)
Invoke-Git @("push", $ForkRemote, $PersonalBranch)

if ($startBranch -ne $MainBranch -and $startBranch -ne $PersonalBranch) {
    Write-Host "[4/4] Returning to $startBranch..." -ForegroundColor Cyan
    Invoke-Git @("checkout", $startBranch)
} else {
    Write-Host "[4/4] Staying on $startBranch." -ForegroundColor Cyan
}

Write-Host "Sync complete." -ForegroundColor Green
