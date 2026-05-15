# Fork Convention

This fork (`pedropaulovc/SolidworksMCP-python`) diverges from the upstream
maintainer's repo (`andrewbartels1/SolidworksMCP-python`) for long-term
personal use while staying easy to merge back and forth.

The convention here is the result of a deliberate setup; if you clone the
fork fresh, run the one-time setup at the bottom of this file.

## Branch model

| Branch | Tracks | Commit policy | Purpose |
|---|---|---|---|
| `main` | upstream `origin/main` exactly | Never commit directly | Clean base for upstream PRs and downstream merges |
| `personal` | branched off `main`, merges `main` forward periodically | Commit freely | Daily working branch — private CI, private skills, customizations |
| `pedro/<topic>` | branched off `personal` | Short-lived | Personal work that's not upstream-bound |
| `feat/...`, `fix/...`, `docs/...` | branched off `main` | Short-lived | Upstream-bound PRs |

Rule of thumb:

- **Want to send a PR upstream?** Branch off `main`, work, push to fork,
  open PR against `andrewbartels1/SolidworksMCP-python`.
- **Want to keep something private?** Branch off `personal` (or just
  commit on `personal`).
- **Want to pull in upstream changes?** Run
  `./scripts/sync-upstream.ps1` (or `.sh`).

## Remote naming

This clone uses an inverted convention versus the usual fork setup:

```
origin = https://github.com/andrewbartels1/SolidworksMCP-python.git  (upstream)
fork   = https://github.com/pedropaulovc/SolidworksMCP-python.git    (this fork)
```

The sync script isolates these names in variables so it stays portable if
you ever rename them.

## What lives on `personal` (and is not meant to go upstream)

- `.github/workflows/pedro-*.yml` — supplementary CI tailored to this
  fork's needs (cross-platform mock-only tests, lint, skip UI tests).
  Files matching `pedro-*` are namespaced so they never collide with
  upstream additions.
- `.claude/skills/personal/` — private Claude skills specific to this
  project. Skills that aren't project-specific should live at
  `~/.claude/skills/` instead, outside this repo entirely.
- `FORK.md`, `scripts/sync-upstream.*`, `.gitattributes` — the
  fork-management plumbing itself.

These paths are listed in `.gitattributes` with `merge=ours`, so an
upstream merge that touches them keeps the fork's version.

## What lives on `main` (and should match upstream exactly)

Everything else. If you want to fix or improve upstream code, branch off
`main`, do the work, open a PR against upstream. Do not commit directly
to `main` — keep it as a clean tracking branch.

## How to send a PR upstream

```powershell
git checkout main
.\scripts\sync-upstream.ps1                    # bring main up to date
git checkout -b feat/your-thing                # off main, not personal
# ...edit, commit...
git push fork feat/your-thing
gh pr create --repo andrewbartels1/SolidworksMCP-python `
    --base main --head pedropaulovc:feat/your-thing
```

The PR will only contain the upstream-relevant diff because the branch
was rooted in `main`, not `personal`. Your private skills and CI never
leak into the PR.

## How to pull upstream changes into your fork

```powershell
.\scripts\sync-upstream.ps1
```

The script:

1. Fetches upstream.
2. Fast-forwards `main` to `origin/main` and pushes to `fork/main`.
3. Merges `main` into `personal` and pushes to `fork/personal`.
4. Returns you to your starting branch.

It refuses to run if the working tree is dirty.

## One-time setup after fresh clone

```powershell
git clone https://github.com/pedropaulovc/SolidworksMCP-python.git
cd SolidworksMCP-python
git remote add upstream https://github.com/andrewbartels1/SolidworksMCP-python.git
# If your `origin` already points at the upstream maintainer's repo, that's
# fine — adjust the variables at the top of scripts/sync-upstream.* to match.
git fetch --all
git config --local merge.ours.driver true   # activates .gitattributes merge=ours
git checkout personal
```

The `merge.ours.driver true` line is the critical part — without it, the
`merge=ours` rules in `.gitattributes` silently fall back to normal
merge and you will hit conflicts on the fork-only files. The sync script
sets this automatically on first run, but it is harmless to set
explicitly.

## What this fork is not trying to do

- It is not trying to delete upstream code (especially not `ui/`). Every
  deletion is a permanent merge-conflict surface; keeping unwanted code
  costs almost nothing.
- It is not trying to replace upstream CI. `pedro-ci.yml` runs alongside
  the upstream `ci.yml`.
- It is not trying to be a hard fork. The goal is long-term coexistence,
  with bidirectional patch flow.

## Open improvements

- [ ] Optional: a pre-commit hook on `personal` that warns when a commit
  touches paths from `.gitattributes` (alerts you that a change will be
  difficult to land upstream).
- [ ] Optional: `.github/dependabot.yml` tuned for the fork's extras.
