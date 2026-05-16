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

- `scripts/provision-fork.sh` — idempotent provisioner for repo
  settings + branch/tag rulesets (modeled on
  `pedropaulovc/typescript-project/scripts/provision-repo.sh`). Run
  once after fork creation, re-run any time the policy needs updating.
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

## SolidWorks COM learnings (from Phase 0 sketch-op PRs, mid-2026)

Collected while implementing the nine sketch primitives in
`andrewbartels1/SolidworksMCP-python#5` (this fork's #1). The full
SolidWorks API doc set lives next to the bundled
`developing-solidworks` skill — read those first. These are the
gotchas that surfaced in *practice* against SOLIDWORKS 2026 +
`pywin32` v311 (the package version observed at the time of writing)
running under Python 3.11 — matching the project's pinned environment
(`solidworks_mcp.yml` pins `python=3.11`; `pyproject.toml` constrains
`pywin32>=306`). The pattern below covers them all:

1. **Look up the COM signature in the bundled API docs before you
   write the call.** The signature in the upstream issue text or the
   surrounding code is sometimes wrong or abbreviated. Match the
   parameter count and types from `developing-solidworks/types/...`.
   *Example:* `ISketchManager::CreatePolygon` is documented as 8
   arguments (`XC, YC, Zc, Xp, Yp, Zp, Sides, Inscribed`); the issue
   spec listed 6. The 6-arg form raised `"Parameter not optional."`
   at the COM boundary on every live call. Fixed in #14.

2. **Flag every dispatch you call a method on, even zero-arg
   methods.** pywin32 late binding resolves zero-arg COM methods as
   tuple-valued properties unless you call
   `sw_type_info.flag_methods(dispatch, "IInterfaceName")` first.
   This applies *per dispatch object*, not per interface globally.
   Symptoms: `'tuple' object is not callable`, `"Member not found."`,
   or silent wrong values. Cases that bit us:
     - `ISelectionMgr.CreateSelectData` — needed for selection-mark
       handling in patterns, mirror, offset.
     - `ISketch.GetSketchSegments` / `GetSketchSegmentsCount2`.
     - `ISketchArc.GetCenterPoint` (used by both circular-pattern
       impl and test readback).
     - `ISketchLine.GetStartPoint2 / GetEndPoint2`.
     - `ISketchEllipse.GetCenterPoint2 / GetMajorPoint2 /
       GetMinorPoint2`.

3. **A `True` return from a SW COM call is *not* a success
   assertion.** SolidWorks routinely returns `True` while placing
   geometry in the wrong location, or returns `False` silently on
   invalid input. Always assert the resulting *geometry*, not just
   the bool. Concrete bug this caught:
   `CreateCircularSketchStepAndRepeat`'s `ArcAngle` parameter is the
   direction *from the seed to the rotation axis*, not a starting
   angle. With `ArcAngle=0` SW returned `True` and our `is_success`
   tests passed — but the visual screenshot showed six circles
   clustered at the seed instead of arrayed around the user's
   `(center_x, center_y)`. The strengthened test reads back each
   instance's centre via `ISketch.GetSketchSegments` plus
   `ISketchArc.GetCenterPoint` and asserts the expected radius. Fixed
   in #17.

4. **A live SolidWorks screenshot is the cheapest catch-all
   assertion.** When a numeric assertion is hard to write, a window
   grab of the SW main window — embedded in the PR body — frequently
   catches placement / orientation / count bugs at review time. The
   COM `IModelDoc2::SaveAs3` image-export path drops in-progress
   sketch geometry, so prefer a Windows GDI window grab of the
   SOLIDWORKS top-level window. The approach: a small Python ctypes
   script that uses `user32.EnumWindows` to locate the SLDWORKS
   top-level window by class/title, then `PrintWindow` (or `BitBlt`
   on the window DC) to copy the client area into a DIB that's
   written to PNG. No script is committed in-tree; build one under
   `scripts/` if you need it.

5. **Selection-based COM methods need marks.** `IModelDoc2::SketchMirror`
   and `ISketchManager::SketchOffset2` / both pattern methods consume
   the *active selection* with no separate "input" argument. SW
   distinguishes the roles of the selected entities by their
   `ISelectData.Mark` value — for example, `SketchMirror` expects
   source segments at mark **1** and the centerline at mark **2**.
   The wrong mark silently no-ops.

6. **`ArcRadius` for circular patterns must be strictly positive.**
   Zero causes `CreateCircularSketchStepAndRepeat` to return `False`
   even when everything else is valid. `ArcRadius` is used only for
   the on-canvas pattern dimension, so the design intent is to clamp
   it to `max(actual_distance_from_seed_to_centre, 1 mm)` — a seed
   sitting exactly on the pattern centre still produces a usable
   call, and a normal seed gets a sensible dimension.

7. **Each PR's screenshots live in `docs/screenshots/` on that PR's
   branch** and are referenced from the PR body via
   `https://raw.githubusercontent.com/.../docs/screenshots/...`. Keep
   the branch alive until the PR merges or the URL 404s.

Add new entries here when you solve a SW automation problem that
wasn't already documented in `developing-solidworks/learnings/`.
