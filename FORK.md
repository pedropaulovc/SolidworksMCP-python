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

Standard fork convention:

```
origin   = https://github.com/pedropaulovc/SolidworksMCP-python.git    (this fork)
upstream = https://github.com/andrewbartels1/SolidworksMCP-python.git  (parent repo)
```

`origin` is your push target. `upstream` is read-only — you fetch from
it via the sync script. If you previously had `origin` pointing at the
parent repo (a non-standard convention), run:

```powershell
git remote rename origin upstream
git remote rename fork origin
```

The sync script isolates the remote names in variables, so if you
deliberately use a different convention you only need to edit the top
of `scripts/sync-upstream.*`.

## What lives on `personal` (and is not meant to go upstream)

- `.github/workflows/pedro-*.yml` — fork-only automation, namespaced so
  it never collides with upstream additions:
    - `pedro-ci.yml` — cross-platform mock-only tests on `personal` and
      `pedro/**`.
    - `pedro-sync-upstream.yml` — daily auto-sync of `upstream/main`
      into `origin/main` and `origin/personal`. Equivalent to running
      `scripts/sync-upstream.ps1` locally.
    - `pedro-prune-merged.yml` — weekly dry-run that lists branches
      whose tip is reachable from `upstream/main` and has no open PR;
      manual trigger with `mode=delete` to actually delete.
    - `pedro-pr-guard.yml` — runs on push to any non-personal branch;
      fails if the diff vs `main` touches fork-only paths. Catches
      "I branched off `personal` instead of `main`" before it ships
      private content to an upstream PR.
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
git push origin feat/your-thing
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

1. Fetches `upstream`.
2. Fast-forwards `main` to `upstream/main` and pushes to `origin/main`.
3. Merges `main` into `personal` and pushes to `origin/personal`.
4. Returns you to your starting branch.

It refuses to run if the working tree is dirty.

## One-time setup after fresh clone

```powershell
git clone https://github.com/pedropaulovc/SolidworksMCP-python.git
cd SolidworksMCP-python
git remote add upstream https://github.com/andrewbartels1/SolidworksMCP-python.git
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
