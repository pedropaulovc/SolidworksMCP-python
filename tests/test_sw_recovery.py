"""Unit tests for :mod:`solidworks_mcp.adapters.sw_recovery`.

Cross-platform (no SolidWorks, no Windows): the process/registry/Win32 helpers
are monkeypatched, so only the pure logic — launch-command construction and
state resolution — is exercised. Runs in the fork's mock-only CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from solidworks_mcp.adapters import sw_recovery as r

pytestmark = pytest.mark.unit


def test_build_connector_launch_command_matches_captured_shape():
    params = r.ConnectorParams(
        space_url="https://tenant-space.3dexperience.3ds.com:443/enovia",
        my_apps_url="https://tenant-compass.3dexperience.3ds.com:443/enovia/resources/AppsMngt",
        registry_url="https://eu1-registry.3dexperience.3ds.com",
        tenant="OI000000000",
    )
    root = Path(r"C:\Program Files\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x")
    cmd = r.build_connector_launch_command(params, root)

    # The exact chain SOLIDWORKS Rx uses (captured via Sysmon).
    assert "CATSTART.exe" in cmd
    assert '-run "SWXDesktopLauncher.exe"' in cmd
    assert "-Url=https://tenant-space.3dexperience.3ds.com:443/enovia" in cmd
    assert f"--AppName={r._APP_NAME}" in cmd
    assert "-tenant=OI000000000" in cmd
    assert "-3DRegistryURL=https://eu1-registry.3dexperience.3ds.com" in cmd
    # -object payload is a single quoted token so CreateProcess keeps it intact.
    assert cmd.count('-object "') == 1


def test_detect_state_not_running(monkeypatch):
    monkeypatch.setattr(r, "_running_images", lambda images: set())
    assert r.detect_state() is r.SolidWorksState.NOT_RUNNING


def test_detect_state_dotnet_wedge(monkeypatch):
    monkeypatch.setattr(r, "_running_images", lambda images: {r.SW_MAIN_PROCESS})
    monkeypatch.setattr(r, "is_dotnet_splash_wedged", lambda: True)
    assert r.detect_state() is r.SolidWorksState.DOTNET_SPLASH_WEDGE


def test_detect_state_connected(monkeypatch):
    monkeypatch.setattr(r, "_running_images", lambda images: {r.SW_MAIN_PROCESS})
    monkeypatch.setattr(r, "is_dotnet_splash_wedged", lambda: False)
    monkeypatch.setattr(
        r, "read_last_run_status",
        lambda: {"CONNECTED_LOAD_STATUS": 2, "SOLIDWORKS_ISCONNECTED": 1},
    )
    assert r.detect_state() is r.SolidWorksState.CONNECTED


def test_detect_state_starting_when_status_zero(monkeypatch):
    monkeypatch.setattr(r, "_running_images", lambda images: {r.SW_MAIN_PROCESS})
    monkeypatch.setattr(r, "is_dotnet_splash_wedged", lambda: False)
    monkeypatch.setattr(r, "com_attach_probe", lambda timeout=5.0: False)
    monkeypatch.setattr(
        r, "read_last_run_status",
        lambda: {"CONNECTED_LOAD_STATUS": 0, "SOLIDWORKS_ISCONNECTED": 0},
    )
    assert r.detect_state() is r.SolidWorksState.STARTING


def test_detect_state_attach_probe_overrides_stale_flags(monkeypatch):
    # The drift a live session hit: flags read CONNECTED_LOAD_STATUS=1 while
    # the instance answered COM attaches instantly. The probe outranks the
    # persistent breadcrumbs on the attach path.
    monkeypatch.setattr(r, "_running_images", lambda images: {r.SW_MAIN_PROCESS})
    monkeypatch.setattr(r, "is_dotnet_splash_wedged", lambda: False)
    monkeypatch.setattr(
        r, "read_last_run_status",
        lambda: {"CONNECTED_LOAD_STATUS": 1, "SOLIDWORKS_ISCONNECTED": 1},
    )
    monkeypatch.setattr(r, "com_attach_probe", lambda timeout=5.0: True)
    assert r.detect_state() is r.SolidWorksState.CONNECTED


def test_detect_state_probe_failure_falls_back_to_flags(monkeypatch):
    monkeypatch.setattr(r, "_running_images", lambda images: {r.SW_MAIN_PROCESS})
    monkeypatch.setattr(r, "is_dotnet_splash_wedged", lambda: False)
    monkeypatch.setattr(r, "com_attach_probe", lambda timeout=5.0: False)
    monkeypatch.setattr(
        r, "read_last_run_status",
        lambda: {"CONNECTED_LOAD_STATUS": 3, "SOLIDWORKS_ISCONNECTED": 0},
    )
    assert r.detect_state() is r.SolidWorksState.RUNNING_DISCONNECTED


def test_com_attach_probe_bounded_by_timeout(monkeypatch):
    # A hung (non-pumping) server can only burn the probe's deadline, never
    # wedge the caller: the probe thread is a daemon the caller abandons.
    import time as _time

    monkeypatch.setattr(r, "_attach_probe_once", lambda: _time.sleep(30) or True)
    start = _time.monotonic()
    assert r.com_attach_probe(timeout=0.2) is False
    assert _time.monotonic() - start < 5.0


def test_com_attach_probe_reports_success(monkeypatch):
    monkeypatch.setattr(r, "_attach_probe_once", lambda: True)
    assert r.com_attach_probe(timeout=2.0) is True


def test_running_images_matches_snapshot_case_insensitively(monkeypatch):
    # No tasklist subprocess: the running set comes from one Toolhelp walk.
    monkeypatch.setattr(
        r, "_snapshot_image_names", lambda: {"sldworks.exe", "notepad.exe"}
    )
    assert r._running_images(("SLDWORKS.EXE", "missing.exe")) == {"SLDWORKS.EXE"}


def test_taskkill_spawns_without_pipes(monkeypatch):
    # The untimed-drain wedge needs an inherited pipe handle; assert taskkill
    # opens none (all stdio DEVNULL) and never uses capture_output.
    captured: dict[str, object] = {}

    class _FakeProc:
        def wait(self, timeout=None):
            captured["waited"] = timeout
            return 0

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _FakeProc()

    monkeypatch.setattr(r.subprocess, "Popen", fake_popen)
    r._taskkill("sldworks.exe", tree=True)

    assert captured["args"] == ["taskkill", "/F", "/IM", "sldworks.exe", "/T"]
    kwargs = captured["kwargs"]
    assert kwargs["stdin"] is r.subprocess.DEVNULL
    assert kwargs["stdout"] is r.subprocess.DEVNULL
    assert kwargs["stderr"] is r.subprocess.DEVNULL
    assert captured["waited"] == 30


def test_is_connector_loaded_requires_live_process(monkeypatch):
    # Stale success flags must NOT read as loaded when sldworks.exe is gone —
    # the false-positive that a live cycle test caught.
    monkeypatch.setattr(
        r, "read_last_run_status",
        lambda: {"CONNECTED_LOAD_STATUS": 2, "SOLIDWORKS_ISCONNECTED": 1},
    )
    monkeypatch.setattr(r, "_running_images", lambda images: set())
    assert r.is_connector_loaded() is False

    monkeypatch.setattr(r, "_running_images", lambda images: {r.SW_MAIN_PROCESS})
    assert r.is_connector_loaded() is True


def test_crash_report_pids_scans_the_crash_handler(monkeypatch):
    # crash_report_pids is just pids_of_image bound to sldexitapp.exe — a NEW pid
    # is the watchdog's crash signal, so it must scan exactly that image.
    calls: list[str] = []

    def fake(image: str) -> set[int]:
        calls.append(image)
        return {4242}

    monkeypatch.setattr(r, "pids_of_image", fake)
    assert r.crash_report_pids() == {4242}
    assert calls == [r.SW_CRASH_HANDLER]


def test_is_sldworks_window_hung_false_when_not_running(monkeypatch):
    # No sldworks.exe => nothing to be hung; the window enumeration is skipped.
    monkeypatch.setattr(r, "pids_of_image", lambda image: set())
    assert r.is_sldworks_window_hung() is False


def test_pids_of_image_empty_off_windows(monkeypatch):
    # The Toolhelp scan is Windows-only; everywhere else it is a benign no-op.
    monkeypatch.setattr(r.os, "name", "posix")
    assert r.pids_of_image("sldworks.exe") == set()


def test_start_refuses_when_already_running(monkeypatch):
    monkeypatch.setattr(r, "_running_images", lambda images: {r.SW_MAIN_PROCESS})
    # Must not attempt a launch (no reset, no Popen) when SW is already up.
    monkeypatch.setattr(
        r, "reset_connector_status",
        lambda: pytest.fail("must not reset when already running"),
    )
    assert r.start_solidworks() is False
