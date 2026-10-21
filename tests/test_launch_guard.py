"""The autouse SolidWorks launch guard refuses every route, and only those.

Every refused call here targets a path that does not exist, and each
assertion is on the guard's own exception, so a guard regression fails the
test instead of reaching a real launch.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from solidworks_mcp.adapters import sw_install, sw_recovery

from . import _launch_guard

pytestmark = pytest.mark.unit

_MISSING_SHORTCUT = Path("X:/launch-guard-test/never-exists/SOLIDWORKS Design.lnk")


@pytest.fixture
def guard(solidworks_launch_guard):
    if solidworks_launch_guard is None:
        pytest.skip(f"{_launch_guard.LIVE_LAUNCH_FLAG} is set; the guard is off")
    # Never reach a real process, even on a guard regression.
    assert isinstance(sw_install.subprocess, _launch_guard.GuardedSubprocess)
    assert isinstance(sw_recovery.subprocess, _launch_guard.GuardedSubprocess)
    if hasattr(os, "startfile"):
        assert os.startfile.__name__ == "refuse_startfile"
    return solidworks_launch_guard


@pytest.fixture
def portable_environment(monkeypatch):
    """Skip the native Windows environment repair so the launch reaches argv."""
    monkeypatch.setattr(sw_install, "solidworks_launch_environment", dict)


def test_platform_shortcut_launch_is_refused(guard, portable_environment) -> None:
    with guard.expect_blocked():
        sw_install.launch_via_platform_shortcut(_MISSING_SHORTCUT)


def test_connector_launch_is_refused(guard) -> None:
    with guard.expect_blocked():
        sw_recovery.subprocess.Popen(
            ["X:/never-exists/CATSTART.exe", "-run", "SWXDesktopLauncher.exe"]
        )


def test_taskkill_of_solidworks_is_refused(guard) -> None:
    with guard.expect_blocked():
        # A made-up image: were the guard broken, taskkill would find nothing.
        sw_recovery.subprocess.run(
            ["taskkill", "/F", "/IM", "sldworks-launch-guard-probe.exe"]
        )


@pytest.mark.skipif(not hasattr(os, "startfile"), reason="os.startfile is Windows-only")
def test_in_process_startfile_is_refused(guard) -> None:
    with guard.expect_blocked():
        os.startfile(str(_MISSING_SHORTCUT))


def test_com_cold_start_is_refused(guard) -> None:
    client = pytest.importorskip("win32com.client")
    with guard.expect_blocked():
        # An unregistered ProgID: were the guard broken, COM fails to resolve it.
        client.Dispatch("SldWorks.LaunchGuardProbe")


def test_swallowed_attempt_is_still_recorded(guard, portable_environment) -> None:
    try:
        sw_install.launch_via_platform_shortcut(_MISSING_SHORTCUT)
    except Exception:
        pass
    assert len(guard.attempts) == 1
    assert "launch_via_platform_shortcut" in guard.attempts[0]
    guard.attempts.clear()


def test_process_table_reads_pass(guard) -> None:
    guard.check_argv("probe", ["tasklist", "/FI", "IMAGENAME eq sldworks.exe"])
    guard.check_argv("probe", 'tasklist /FI "IMAGENAME eq sldworks.exe"')
    assert guard.attempts == []


def test_unrelated_subprocess_passes(guard) -> None:
    result = sw_install.subprocess.run(
        [sys.executable, "-c", "print('ok')"], capture_output=True, text=True
    )
    assert result.stdout.strip() == "ok"
    assert guard.attempts == []


@pytest.mark.parametrize(
    ("value", "allowed"),
    [("", False), ("0", False), ("false", False), ("1", True), ("true", True)],
)
def test_live_flag_controls_the_guard(value: str, allowed: bool) -> None:
    environ = {_launch_guard.LIVE_LAUNCH_FLAG: value}
    assert _launch_guard.live_launch_allowed(environ) is allowed
