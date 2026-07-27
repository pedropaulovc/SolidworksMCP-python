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
    monkeypatch.setattr(
        r, "read_last_run_status",
        lambda: {"CONNECTED_LOAD_STATUS": 0, "SOLIDWORKS_ISCONNECTED": 0},
    )
    assert r.detect_state() is r.SolidWorksState.STARTING


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


def test_start_refuses_when_already_running(monkeypatch):
    monkeypatch.setattr(r, "_running_images", lambda images: {r.SW_MAIN_PROCESS})
    # Must not attempt a launch (no reset, no Popen) when SW is already up.
    monkeypatch.setattr(
        r, "reset_connector_status",
        lambda: pytest.fail("must not reset when already running"),
    )
    assert r.start_solidworks() is False
