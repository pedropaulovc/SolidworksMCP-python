# SolidWorks MCP Server (Python)

This file is the quick orientation guide for contributors and coding agents.

## Fork layout — read this before branching

This checkout is `pedropaulovc/SolidworksMCP-python`, a fork of
`andrewbartels1/SolidworksMCP-python`. **`FORK.md` is authoritative**
for branch conventions, remote naming, sync, and what lives on
`personal` vs `main`. Read it before creating branches or PRs.

Quick rules to keep CI green:

- **Upstream-bound PR** (going to `andrewbartels1/...`): branch off
  `main`, name `feat/...` / `fix/...` / `docs/...`. The
  `pedro-pr-guard` workflow fails if such a branch carries fork-only
  paths (`FORK.md`, `pedro-*.yml`, `sync-upstream.*`,
  `provision-fork.sh`, `.claude/skills/personal/`).
- **Personal / fork-only PR** (going to `personal` on the fork):
  branch off `personal`, name `pedro/<topic>`. The guard ignores
  `personal` and `pedro/**` so the inherited fork-only files don't
  trip it.
- Don't use unprefixed branch names (`worktree-add-*`, `experiment-*`,
  etc.) for personal work — the guard will flag them.

Sync upstream changes into the fork with
`./scripts/sync-upstream.ps1` (or `.sh`).

## Platform and Runtime

- Primary runtime is Python 3.11+.
- Real COM automation requires Windows + SolidWorks installed.
- Cross-platform development is possible in mock/test mode.

## Build and Development Commands

Use either micromamba environment commands or local virtualenv commands.

### Preferred PowerShell workflow

```powershell
# Show command help
.\dev-commands.ps1

# Full install in micromamba env
.\dev-commands.ps1 dev-install

# Fast test pass (no SolidWorks-required tests)
.\dev-commands.ps1 dev-test

# Full test run including real SolidWorks integration
.\dev-commands.ps1 dev-test-full

# Lint and format
.\dev-commands.ps1 dev-lint
.\dev-commands.ps1 dev-format

# Docs build/serve
.\dev-commands.ps1 dev-docs-build
.\dev-commands.ps1 dev-docs-strict
.\dev-commands.ps1 dev-docs-audit
.\dev-commands.ps1 dev-docs
```

### Virtualenv direct workflow

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.\.venv\Scripts\python.exe -m pip install -e ".[dev,test,docs]"

# Run server
.\.venv\Scripts\python.exe -m solidworks_mcp.server

# Lint/tests/docs
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m pytest tests -m "not solidworks_only"
.\.venv\Scripts\python.exe -m mkdocs build --clean
```

## Architecture

- Server entrypoint: `src/solidworks_mcp/server.py`
- CLI entrypoint: `src/solidworks_mcp/server_cli_fixed.py`
- Adapters: `src/solidworks_mcp/adapters/`
  - `pywin32_adapter.py`: real SolidWorks COM adapter (Windows)
  - `mock_adapter.py`: mock adapter for tests and CI-like runs
  - `factory.py`: adapter selection/routing logic
- Tools: `src/solidworks_mcp/tools/` (modeling, sketching, drawing, export, analysis, automation, templates, VBA, docs discovery)
- Agent harness: `src/solidworks_mcp/agents/` (prompt schemas, smoke test CLI, run/error persistence)

## Key Patterns

### COM and Adapter Safety

- Prefer adapter abstraction, not direct COM calls from tool modules.
- Keep Windows/COM behavior behind adapter boundaries.
- Use mock adapter for tests unless a test explicitly requires real SolidWorks.

### Logging and Output

- Use project logging utilities (`loguru`/configured helpers).
- Avoid ad-hoc print statements in runtime server paths.

### Validation and Tool Contracts

- Keep tool input schemas strict and explicit.
- Maintain stable response payload shapes (`status`, `message`, `execution_time`, plus data payload).

## Testing Guidance

- Default local path: run non-`solidworks_only` tests first.
- Real integration path: run `dev-test-full` on Windows with SolidWorks available.
- Harness and generated report artifacts may write under `tests/.generated/` and `.solidworks_mcp/`.

## Documentation Guidance

- Build docs before commit when touching docs pages:
  - `.\dev-commands.ps1 dev-docs-build`
  - `.\dev-commands.ps1 dev-docs-strict`
- For local preview:
  - `.\dev-commands.ps1 dev-docs`

## Agent and Model Notes

- VS Code Copilot subscription is suitable for chat-based workflows.
- Local Python smoke tests require explicit provider credentials:
  - GitHub Models: `GH_TOKEN` or `GITHUB_API_KEY`
  - OpenAI: `OPENAI_API_KEY`
  - Anthropic: `ANTHROPIC_API_KEY`

## Troubleshooting Runbook

When the bridge misbehaves, walk this list in order. Compiled from SolidWorks
forum threads, pywin32 issues, and observed failures on this install. Last
updated 2026-04-24.

### 1. `OpenDoc6` HRESULT failure — pass-by-ref params

- **Cause:** pywin32 `makepy`/`gencache` marks SW's pass-by-ref `errors` and
  `warnings` parameters as non-optional inputs. Calls fail unless
  `pythoncom.Missing` is passed explicitly.
- **Check:** grep server code for `OpenDoc6(`; every callsite should pass
  `pythoncom.Missing` for the last two params.
- **Fix:**
  `model, errors, warnings = sw.OpenDoc6(path, type, opts, '', pythoncom.Missing, pythoncom.Missing)`
- **Error codes:** warning=128 = already open (not fatal); error=1024 = generic
  open failure. S_OK with null return is also possible.

### 2. `Member not found` / `NoneType not callable` — stale gencache

- **Cause:** pywin32 caches SW type-library wrappers under `%TEMP%\gen_py\`.
  SW upgrades (e.g. 2024 → 2025) or patches leave wrappers pointing at the
  old TLB.
- **Fix:** delete `%TEMP%\gen_py\`, restart the MCP server. Rebuilds on first
  call.

### 3. `No active model` AND `OpenDoc6` errors together — stale COM handle

- **Cause:** MCP server process grabbed a COM pointer at startup; user has
  since quit and reopened SolidWorks. Pointer is dangling.
- **Check:** compare MCP server start time (Claude `main.log` →
  `Launching MCP Server: solidworks`) to current `SLDWORKS.exe` start time.
- **Fix:** restart Claude Desktop (respawns MCP server, which grabs a fresh
  SW handle). Restarting SolidWorks alone will NOT fix this.

### 4. `Circuit breaker is open for <tool>`

- **Cause:** server-side resilience library trips after N failures in a
  window. Subsequent calls fail fast even when the underlying issue is fixed.
- **Fix:** wait for breaker timeout (~30–60s) or restart the server.

### 5. COM apartment / threading mismatch — FastMCP async workers

- **Cause:** SolidWorks COM is STA (single-threaded apartment). An IDispatch
  proxy obtained on thread A cannot be invoked from thread B. FastMCP runs
  tool handlers on worker threads distinct from where `connect()` ran.
- **Signature (critical):** pywin32 late-binding surfaces this as
  ``AttributeError: SldWorks.Application.<method>`` at attribute lookup —
  **NOT** as ``pywintypes.com_error``. The `except com_error` branch in
  ``_handle_com_operation`` therefore misses it, and the generic handler
  flattens the message to the source+method name with no traceback.
- **Fix (applied 2026-04-24, revised same day):** dedicated STA worker
  thread. See "COM threading architecture" section below. The earlier
  thread-local fix (`_tls` / `_swapp_for_thread`) was a band-aid that was
  replaced by the proper executor-based design.

### 6. PDM vault files

- **Cause:** `OpenDoc6` on a file under a PDM working folder fails when the
  file isn't checked out or cached locally.
- **Check:** target path has PDM vault metadata / is under a PDM working
  folder.
- **Fix:** check the file out in PDM, or test with a copy outside the vault.

### 7. Silent-mode UI leak

- `swOpenDocOptions_Silent` still pops the UI on some SW-2025 SP levels.
  Cosmetic only; not a failure.

### 8. SW 2025 SP0 drawing crashes

- SP0 has reported `.slddrw` open crashes. If the target is a drawing,
  suggest upgrading to SP1+.

### 9. MCP log silence

- FastMCP banner output (emoji-prefixed lines to stdout) is misparsed as
  JSON-RPC by the Claude host — noise, not errors.
- Actual tool-call tracebacks go to **stderr** and are NOT captured in
  `%APPDATA%\Claude\logs\mcp-server-solidworks.log`. Check the
  `%LOCALAPPDATA%\solidworks_mcp\logs\` directory and the FastMCP install
  dir for a separate Python log.

### 10. Claude Code `settings.json` UTF-8 BOM (host-side, not SW)

- A BOM on `~/.claude/settings.json` makes Claude Code silently drop **all**
  user settings (`[SettingsIo] Failed to read ... Unexpected token '﻿'`).
  Strip the BOM; write plain UTF-8.

### 11. 3DEXPERIENCE "for Makers" edition — cold-start dialog on connect

- **Cause:** the "for Makers" edition (registered COM server under
  `...\SOLIDWORKS 3DEXPERIENCE R<year>x\...`) refuses any cold start that is
  not the Platform shortcut. Cold-starting `SldWorks.Application` via COM
  `Dispatch` (or running `sldworks.exe`) pops the modal "SOLIDWORKS Design
  must be launched from the 3DEXPERIENCE Platform…" dialog and exits without
  registering a usable COM server.
- **Fix (applied):** `adapters/sw_install.py` resolves a launch strategy from
  the registered edition. `acquire_solidworks_application` (and
  `docs_discovery.connect_to_solidworks`) always attach to a running instance
  first; when none is running, the Makers edition is started via the Platform
  Start-menu shortcut (`Dassault Systemes SOLIDWORKS 3DEXPERIENCE*/SOLIDWORKS
  Design.lnk`) and then attached. Standard installs still cold-start via COM.
  If the edition is Makers but no shortcut is found, an actionable error is
  raised instead of triggering the dialog.
  - The registry stores `LocalServer32` as an 8.3 short path
    (`...\SOLIDW~1\...`) that hides the `3DEXPERIENCE` marker, so the path is
    expanded via `GetLongPathNameW` before the edition check.
  - Before any launch, `is_solidworks_process_running()` (a `tasklist` probe)
    short-circuits: if an `sldworks.exe` is already up but not yet
    COM-attachable, the code polls for attach instead of starting a second
    instance — otherwise the second launch pops the "Another session of
    SOLIDWORKS may already be running / journal file could not be created"
    warning.
- **Check:** `python -c "from solidworks_mcp.adapters import sw_install;
  print(sw_install.resolve_launch_strategy())"`.

### Decision order when starting a debug session

1. Read recent `%APPDATA%\Claude\logs\main.log` entries for
   `Launching MCP Server: solidworks` and note the timestamp.
2. Compare to current `SLDWORKS.exe` process start (Task Manager). If SW is
   newer than the server → **#3**, restart Claude Desktop first.
3. If SW is older or same, try a trivial call (`get_model_info`). If it
   returns a circuit-breaker error, wait 60s and retry → **#4**.
4. If real error text surfaces, map to #1/#2/#5/#6 via the error signature
   above.
5. Only then read server source to confirm.

## COM threading architecture

Invariants every new COM-touching code path must respect. Written 2026-04-24
after the Phase 1+2 rewrite landed.

### 1. All COM calls run on the adapter's ComExecutor thread

The adapter owns a single dedicated worker thread (``PyWin32Adapter._com``,
instance of ``com_executor.ComExecutor``). COM is initialized on that thread
once via ``pythoncom.CoInitialize()``. All COM work — ``connect()``, every
``_handle_com_operation`` closure, every ``disconnect()`` cleanup — is
submitted to that executor and awaited via ``Future``.

Consequences:

- ``self.swApp`` and ``self.currentModel`` are **only** valid when touched
  from inside an executor job. Reading them from an async tool function
  or an HTTP handler thread directly will raise the cross-thread
  ``AttributeError`` described in runbook item #5.
- Do NOT call ``pythoncom.CoInitialize()`` anywhere else in the adapter
  code. The executor owns the apartment.
- Do NOT cache IDispatch references outside instance attributes that are
  only read from executor jobs.

### 2. Early binding is the default, via a checked-in makepy wrapper

``_do_connect`` acquires the app and wraps it in the generated ``ISldWorks``
class (``_early_bound_application`` → ``sw_type_info.early_bound(raw,
"ISldWorks")``). The interface classes come from a **checked-in** makepy
wrapper — ``adapters/_generated/sldworks_2026.py`` — imported by
``sw_type_info`` at load time, so startup never depends on a writable
``%TEMP%\gen_py\`` or on typelib discovery through a ROT proxy. Regenerate it
with ``scripts/generate_solidworks_stubs.py`` / plain
``python -m win32com.client.makepy`` only after a SW version bump; SW keeps
automation-interface IIDs and DISPIDs binary-compatible across releases, so the
2026 wrapper binds older seats too.

**Why early binding — the old "late binding is forced, always" rationale was
wrong.** The claim was that early-bound wrappers reject the VARIANT pass-by-ref
out-parameters used by ``OpenDoc6``. They do not: makepy invokes by DISPID
through ``InvokeTypes``, which describes each ``[out]`` param from the typelib
and returns it in the result tuple — ``OpenDoc6`` works early-bound with
``pythoncom.Missing`` for the trailing ``errors``/``warnings`` exactly as it did
late-bound. Early binding also **skips** the per-name ``GetIDsOfNames`` /
``_FlagAsMethod`` round-trips that ``flag_methods`` pays (~155 ms per object) —
that overhead was ~90% of the drawing-layout audit (issue #277) and a steady tax
on every part build, which is the whole reason for the migration.

If you add a new COM-touching function, wrap acquired dispatches through
``sw_type_info.early_bound`` / ``early_bound_or_flag`` (below), **not**
``dynamic.Dispatch`` and **not** bare ``EnsureDispatch`` (the latter fails on
SolidWorks's ROT proxy with ``-2147319765 Element not found`` — dispatch a
ProgID/ROT object first, then apply the generated class via its ``_oleobj_``).

### 3. Early binding via sw_type_info

``sw_type_info.early_bound(obj, "IFace2")`` returns ``obj`` wrapped in the
makepy interface class, invoking declared members by DISPID. Use
``early_bound_or_flag(obj, "IFace2", *fallback_zero_arg_names)`` at call sites:
it early-binds when the wrapper is present (the normal case) and, only if that
interface class is unavailable, falls back to flagging the named methods.
Because ``obj`` is wrapped into a **new** object, the result must be
**reassigned** — ``x = early_bound_or_flag(x, ...)`` — a discarded result is a
silent no-op. (In this repo's build scripts use the ``_common._early_bound``
shim.)

**Off-interface members are safe.** A makepy class exposes only ITS interface's
members, but SW dispatches are polymorphic: a face is an ``IFace2`` *and* an
``IEntity`` (``Select2``); a part model answers ``IModelDoc2`` *and*
``IPartDoc`` (``GetBodies2``). ``early_bound`` returns a
``_fallback_subclass`` whose ``__getattr__``/``__setattr__`` forward any member
the named class does not declare to a lazily-built late-bound dispatch on the
same ``_oleobj_``. So you do **not** have to prove each call site touches only
one interface, and you never need to flag "just in case". (The manual
alternative is ``win32com.client.CastTo(obj, "IEntity")`` per off-interface
call; the fallback automates it.)

``flag_methods`` / ``flagged`` / ``flag_doc`` remain only where early binding
can't apply: interfaces **absent from ``sldworks.tlb``** (the undocumented
motion methods — see ``adapters/solidworks/motion.py``, which uses
``flag_method_names``), and a few sketch-entity property/method "drift" cases.
Prefer early binding everywhere else.

### 4. Properties are still properties

Not every zero-arg accessor is a method. ``IConfiguration.Name``,
``ModelDoc2.Visible``, etc. are genuine properties — read them without
``()``. The early-bound wrapper resolves them correctly (makepy properties go
through ``_prop_map_get_`` / ``_prop_map_put_``, methods are real ``def``\\ s in
the class body), so you no longer have to reason about method-vs-property
flagging for declared members. The distinction still matters when you pass
``*fallback_zero_arg_names`` to ``early_bound_or_flag`` (pass only zero-arg
methods, never a property name) and in the rare ``flag_*`` fallbacks above.

### 5. Regression tests

See ``tests/test_live_sw_regression.py`` for the safety net:

- ComExecutor start/stop/exception semantics
- flag_methods incrementality + per-interface correctness (the fallback path)
- early-bound ``swApp`` acquisition (``ISldWorks`` wrapper via ``early_bound``)
- ``get_model_info`` fields populate correctly
- ``get_model_info`` works from a worker thread (the cross-thread bug
  reproducer)

Run these after any change to ``pywin32_adapter.py``, ``com_executor.py``,
or ``sw_type_info.py``::

    $env:SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1
    .\.venv\Scripts\python.exe -m pytest tests/test_live_sw_regression.py -v

### Reference sources

- [Problem with OpenDoc6 — SW Forums](https://forum.solidworks.com/thread/19519)
- [OpenDoc6 error — SW Forums](https://forum.solidworks.com/thread/100254)
- [Opendoc6/7 silent open — SW Forums](https://forum.solidworks.com/thread/245676)
- [pywin32 #337 SW pass-by-reference bug](https://sourceforge.net/p/pywin32/bugs/337/)
- [pywin32 #1585 strange issues with SW](https://github.com/mhammond/pywin32/issues/1585)
- [CodeStack SW macros troubleshooting](https://www.codestack.net/solidworks-api/troubleshooting/macros/)
- [SW 2025 SP0 drawing crash thread](https://forum.solidworks.com/forum-solidworks/MYfrK4r0RF6Fnd8tf5tAMA/solidworks-2025-sp0-crashes-when-opening-a-drawing-file)
- [pythoncom CoInitializeEx docs](https://timgolden.me.uk/pywin32-docs/pythoncom__CoInitializeEx_meth.html)
