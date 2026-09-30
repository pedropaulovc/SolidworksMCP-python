"""Refuse every route by which a test could start or kill SolidWorks.

A developer seat and a farm worker can share one SolidWorks licence, so a test
that reaches a real launch steals that licence mid-build. On 2026-09-25 a
root-level ``pytest`` of the harmonic-analyzer repository collected this suite
and started SolidWorks on a developer PC through the 3DEXPERIENCE Start-menu
shortcut: ``test_all_endpoints_harness.py``'s smoke tests call the
``discover_solidworks_docs`` tool, whose ``connect_to_solidworks`` falls
through to ``sw_install.launch_via_platform_shortcut`` when nothing is running.

The guard is installed for every test by an autouse fixture in ``conftest.py``.
It covers the four routes the package uses:

* ``subprocess.run`` / ``Popen`` / ``call`` / ``check_call`` /
  ``check_output`` as seen by ``sw_install`` and ``sw_recovery``: argv naming
  ``os.startfile``, a ``.lnk``, ``CATSTART``, ``SWXDesktopLauncher`` or
  ``sldworks`` is refused. ``tasklist`` stays allowed because it only reads the
  process table. The launch itself happens in a ``python -I -c`` child, so
  patching ``os.startfile`` in this process alone would not stop it.
* ``os.startfile`` in this process.
* ``win32com.client.Dispatch`` / ``DispatchEx`` / ``gencache.EnsureDispatch`` /
  ``dynamic.Dispatch`` with a ``SldWorks`` ProgID, which cold-starts
  SolidWorks through its COM LocalServer.

A refused call raises :class:`SolidWorksLaunchBlocked` with the caller's stack,
and it is also recorded: many call sites catch ``Exception``, so the fixture
fails the test at teardown if any attempt was recorded, even one the code under
test swallowed. Set ``SOLIDWORKS_MCP_RUN_REAL_INTEGRATION=1`` (the flag that
already gates every live suite) to disable the guard for deliberate live runs.
"""

from __future__ import annotations

import os
import subprocess
import traceback
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import PureWindowsPath
from typing import Any

import pytest

LIVE_LAUNCH_FLAG = "SOLIDWORKS_MCP_RUN_REAL_INTEGRATION"

_LAUNCH_MARKERS = (
    "startfile",
    ".lnk",
    "catstart",
    "swxdesktoplauncher",
    "sldworks",
)
_READ_ONLY_PROGRAMS = frozenset({"tasklist", "tasklist.exe"})
_SUBPROCESS_ROUTES = ("run", "Popen", "call", "check_call", "check_output")


class SolidWorksLaunchBlocked(RuntimeError):
    """A test tried to start or kill SolidWorks without the live opt-in."""


def live_launch_allowed(environ: Mapping[str, str]) -> bool:
    """Report whether the environment opts in to real SolidWorks launches."""
    value = environ.get(LIVE_LAUNCH_FLAG, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _argv_text(args: Any) -> str:
    if isinstance(args, (list, tuple)):
        return " ".join(str(part) for part in args)
    return str(args)


def _program(args: Any) -> str:
    if isinstance(args, (list, tuple)):
        first = str(args[0]) if args else ""
        return PureWindowsPath(first).name.lower()
    words = str(args).split()
    if not words:
        return ""
    return PureWindowsPath(words[0].strip('"')).name.lower()


class LaunchGuard:
    """Records and refuses SolidWorks launch attempts for one test."""

    blocked_error = SolidWorksLaunchBlocked

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def refuse(self, route: str, detail: str) -> None:
        stack = "".join(traceback.format_stack(limit=25)[:-2])
        test = os.environ.get("PYTEST_CURRENT_TEST", "<no test>")
        message = (
            f"SolidWorks launch blocked in {test} via {route}: {detail[:300]}\n"
            f"Set {LIVE_LAUNCH_FLAG}=1 only for a deliberate live run.\n"
            f"Caller stack:\n{stack}"
        )
        self.attempts.append(message)
        raise SolidWorksLaunchBlocked(message)

    def check_argv(self, route: str, args: Any) -> None:
        if _program(args) in _READ_ONLY_PROGRAMS:
            return
        text = _argv_text(args)
        lowered = text.lower()
        if any(marker in lowered for marker in _LAUNCH_MARKERS):
            self.refuse(route, text)

    def check_progid(self, route: str, progid: Any) -> None:
        if isinstance(progid, str) and "sldworks" in progid.lower():
            self.refuse(route, progid)

    @contextmanager
    def expect_blocked(self) -> Iterator[None]:
        """Assert that the block raises the guard's error, then forget it."""
        before = len(self.attempts)
        with pytest.raises(SolidWorksLaunchBlocked):
            yield
        assert len(self.attempts) == before + 1
        del self.attempts[before:]


class GuardedSubprocess:
    """``subprocess`` stand-in for the launch modules; everything else forwards."""

    def __init__(self, real: Any, guard: LaunchGuard) -> None:
        self._real = real
        self._guard = guard
        for route in _SUBPROCESS_ROUTES:
            setattr(self, route, self._guarded(route))

    def _guarded(self, route: str) -> Any:
        original = getattr(self._real, route)

        def guarded(args: Any, *rest: Any, **kwargs: Any) -> Any:
            self._guard.check_argv(f"subprocess.{route}", args)
            return original(args, *rest, **kwargs)

        return guarded

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def install(monkeypatch: pytest.MonkeyPatch, guard: LaunchGuard) -> None:
    """Patch every launch route for the current test."""
    from solidworks_mcp.adapters import sw_install, sw_recovery

    for module in (sw_install, sw_recovery):
        monkeypatch.setattr(module, "subprocess", GuardedSubprocess(subprocess, guard))

    if hasattr(os, "startfile"):

        def refuse_startfile(path: Any, *args: Any, **kwargs: Any) -> None:
            guard.refuse("os.startfile", str(path))

        monkeypatch.setattr(os, "startfile", refuse_startfile)

    try:
        import win32com.client
        import win32com.client.dynamic
        import win32com.client.gencache
    except ImportError:
        return

    targets = (
        (win32com.client, "Dispatch"),
        (win32com.client, "DispatchEx"),
        (win32com.client.gencache, "EnsureDispatch"),
        (win32com.client.dynamic, "Dispatch"),
    )
    for owner, name in targets:
        original = getattr(owner, name, None)
        if original is None:
            continue
        monkeypatch.setattr(
            owner, name, _guarded_dispatch(guard, owner, name, original)
        )


def _guarded_dispatch(guard: LaunchGuard, owner: Any, name: str, original: Any) -> Any:
    route = f"{owner.__name__}.{name}"

    def guarded(progid: Any, *args: Any, **kwargs: Any) -> Any:
        guard.check_progid(route, progid)
        return original(progid, *args, **kwargs)

    return guarded
