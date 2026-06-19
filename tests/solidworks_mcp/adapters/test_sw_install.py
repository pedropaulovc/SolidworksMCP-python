"""Unit tests for SolidWorks edition detection and launch-strategy resolution.

These are platform-agnostic: every Windows-only seam (``winreg``,
``os.startfile``) is monkeypatched, so the suite runs identically on Linux CI.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters import sw_install
from solidworks_mcp.adapters.sw_install import LaunchStrategy


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (r'"C:\Program Files\SW\sldworks.exe" /automation', r"C:\Program Files\SW\sldworks.exe"),
        (r"C:\Program Files\SW\sldworks.exe /regserver", r"C:\Program Files\SW\sldworks.exe"),
        (r"C:\Program Files\SW\sldworks.exe", r"C:\Program Files\SW\sldworks.exe"),
        (r"C:\Program Files\SW\sldworks", r"C:\Program Files\SW\sldworks"),
        ("   ", None),
        (None, None),
    ],
)
def test_strip_server_command(command: str | None, expected: str | None) -> None:
    """The bare .exe path is extracted from quoted/switched LocalServer32 commands."""
    assert sw_install._strip_server_command(command) == expected


@pytest.mark.parametrize(
    ("exe_path", "expected"),
    [
        (r"C:\Program Files\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x\SOLIDWORKS\sldworks.exe", True),
        (r"C:\Program Files\Dassault Systemes\SOLIDWORKS 3dexperience r2026x\sldworks.exe", True),
        (r"C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\sldworks.exe", False),
        ("", False),
        (None, False),
    ],
)
def test_is_3dexperience_install(exe_path: str | None, expected: bool) -> None:
    """3DEXPERIENCE installs are flagged by the marker in the server path."""
    assert sw_install.is_3dexperience_install(exe_path) is expected


def test_resolve_com_server_path_none_without_winreg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without winreg (non-Windows) the server path resolves to None, not an error."""
    monkeypatch.setattr(sw_install, "winreg", None)
    assert sw_install.resolve_com_server_path() is None


def test_resolve_com_server_path_none_when_progid_unregistered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No SldWorks.Application CLSID registered → None."""
    monkeypatch.setattr(sw_install, "winreg", SimpleNamespace(HKEY_CLASSES_ROOT=0))
    monkeypatch.setattr(sw_install, "_read_default_value", lambda _root, _sub: None)
    assert sw_install.resolve_com_server_path() is None


def test_resolve_com_server_path_none_when_no_localserver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLSID resolves but LocalServer32 is empty → None."""
    monkeypatch.setattr(sw_install, "winreg", SimpleNamespace(HKEY_CLASSES_ROOT=0))
    monkeypatch.setattr(
        sw_install,
        "_read_default_value",
        lambda _root, sub: "{CLSID}" if sub.endswith("CLSID") else None,
    )
    assert sw_install.resolve_com_server_path() is None


def test_read_default_value_success_and_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_read_default_value reads the (Default) value and tolerates a missing key."""

    @contextmanager
    def _open_key(_root, subkey):
        if subkey == "present":
            yield "handle"
        else:
            raise OSError("missing key")

    fake_winreg = SimpleNamespace(
        OpenKey=_open_key,
        QueryValueEx=lambda _handle, _name: (r"  C:\sw\sldworks.exe  ", 1),
    )
    monkeypatch.setattr(sw_install, "winreg", fake_winreg)

    assert sw_install._read_default_value(0, "present") == r"C:\sw\sldworks.exe"
    assert sw_install._read_default_value(0, "absent") is None


def test_start_menu_program_dirs_filters_to_existing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Only existing Programs trees are returned; missing env vars are skipped."""
    existing = tmp_path / "all-users"
    (existing / "Microsoft" / "Windows" / "Start Menu" / "Programs").mkdir(parents=True)
    monkeypatch.setattr(
        sw_install.os,
        "environ",
        {"ProgramData": str(existing)},  # APPDATA absent
    )
    dirs = sw_install._start_menu_program_dirs()
    assert dirs == [existing / "Microsoft" / "Windows" / "Start Menu" / "Programs"]


@pytest.mark.skipif(os.name != "nt", reason="GetLongPathNameW is Windows-only")
def test_expand_short_path_on_windows(tmp_path: Path) -> None:
    """On Windows an existing path round-trips; a missing path is returned unchanged."""
    real = tmp_path / "sldworks.exe"
    real.write_text("")
    assert sw_install._expand_short_path(str(real)) == str(real)

    missing = str(tmp_path / "does-not-exist.exe")
    assert sw_install._expand_short_path(missing) == missing


def test_expand_short_path_noop_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Off Windows, short-path expansion returns the input unchanged."""
    monkeypatch.setattr(sw_install.os, "name", "posix")
    assert sw_install._expand_short_path(r"C:\PROGRA~1\SW\sldworks.exe") == (
        r"C:\PROGRA~1\SW\sldworks.exe"
    )


def test_resolve_com_server_path_expands_short_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 8.3 short path from the registry is expanded so the 3DX marker survives."""
    short = r"C:\PROGRA~1\DASSAU~1\SOLIDW~1\SLDWORKS.exe"
    full = r"C:\Program Files\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x\sldworks.exe"
    monkeypatch.setattr(sw_install, "_read_default_value", lambda _root, sub: (
        "{CLSID}" if sub.endswith("CLSID") else short
    ))
    monkeypatch.setattr(sw_install, "_expand_short_path", lambda p: full if p == short else p)

    resolved = sw_install.resolve_com_server_path()
    assert resolved == full
    assert sw_install.is_3dexperience_install(resolved) is True


def _make_shortcut(programs: Path, release: str) -> Path:
    """Create a fake Platform launch shortcut under a Start-menu Programs dir."""
    folder = programs / f"Dassault Systemes SOLIDWORKS 3DEXPERIENCE {release}"
    folder.mkdir(parents=True, exist_ok=True)
    shortcut = folder / "SOLIDWORKS Design.lnk"
    shortcut.write_text("")
    return shortcut


def test_find_platform_shortcut_prefers_newest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When several releases are installed, the newest R<year>x wins."""
    programs = tmp_path / "Programs"
    _make_shortcut(programs, "R2025x")
    newest = _make_shortcut(programs, "R2026x")
    monkeypatch.setattr(sw_install, "_start_menu_program_dirs", lambda: [programs])

    assert sw_install.find_platform_shortcut() == newest


def test_find_platform_shortcut_none_when_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No shortcut tree yields None."""
    monkeypatch.setattr(sw_install, "_start_menu_program_dirs", lambda: [tmp_path])
    assert sw_install.find_platform_shortcut() is None


def test_resolve_launch_strategy_standard(monkeypatch: pytest.MonkeyPatch) -> None:
    """A standard install cold-starts via COM Dispatch."""
    monkeypatch.setattr(
        sw_install, "resolve_com_server_path", lambda: r"C:\SW\sldworks.exe"
    )
    assert sw_install.resolve_launch_strategy() == (LaunchStrategy.COM_DISPATCH, None)


def test_resolve_launch_strategy_makers_with_shortcut(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Makers install with a shortcut routes to the Platform shortcut."""
    shortcut = tmp_path / "SOLIDWORKS Design.lnk"
    monkeypatch.setattr(
        sw_install,
        "resolve_com_server_path",
        lambda: r"C:\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x\sldworks.exe",
    )
    monkeypatch.setattr(sw_install, "find_platform_shortcut", lambda: shortcut)

    assert sw_install.resolve_launch_strategy() == (
        LaunchStrategy.PLATFORM_SHORTCUT,
        shortcut,
    )


def test_resolve_launch_strategy_makers_without_shortcut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Makers install with no shortcut requires manual Platform launch."""
    monkeypatch.setattr(
        sw_install,
        "resolve_com_server_path",
        lambda: r"C:\Dassault Systemes\SOLIDWORKS 3DEXPERIENCE R2026x\sldworks.exe",
    )
    monkeypatch.setattr(sw_install, "find_platform_shortcut", lambda: None)

    assert sw_install.resolve_launch_strategy() == (
        LaunchStrategy.PLATFORM_REQUIRED,
        None,
    )


def test_is_solidworks_process_running_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off Windows the process check short-circuits to False."""
    monkeypatch.setattr(sw_install.os, "name", "posix")
    assert sw_install.is_solidworks_process_running() is False


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('"sldworks.exe","1234","Console"', True),
        ("INFO: No tasks are running which match the specified criteria.", False),
    ],
)
def test_is_solidworks_process_running_parses_tasklist(
    monkeypatch: pytest.MonkeyPatch, stdout: str, expected: bool
) -> None:
    """The tasklist output is parsed case-insensitively for the SW image name."""
    monkeypatch.setattr(sw_install.os, "name", "nt")
    monkeypatch.setattr(
        sw_install.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(stdout=stdout),
    )
    assert sw_install.is_solidworks_process_running() is expected


def test_launch_via_platform_shortcut_uses_startfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The shortcut is opened through os.startfile (Windows shell handoff)."""
    calls: list[str] = []
    monkeypatch.setattr(sw_install.os, "startfile", calls.append, raising=False)

    sw_install.launch_via_platform_shortcut(Path(r"C:\sw\SOLIDWORKS Design.lnk"))

    assert calls == [r"C:\sw\SOLIDWORKS Design.lnk"]
