"""Only missing Windows standard variables are recovered for launch children."""

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from solidworks_mcp.adapters import sw_install, sw_recovery
from solidworks_mcp.adapters import sw_launch_env as environment_module

STANDARD = {
    "CommonProgramFiles": r"D:\Programs\Common Files",
    "CommonProgramW6432": r"D:\Programs\Common Files",
    "CommonProgramFiles(x86)": r"D:\Programs32\Common Files",
    "PROCESSOR_ARCHITECTURE": "AMD64",
}


def test_connector_launch_receives_child_environment_without_losing_task_context(
    monkeypatch,
):
    parent = {
        "HARMONIC_COM_SEAT": "owned",
        "OTEL_SERVICE_NAME": "test",
        "PRIVATE_TOKEN": "private-value",
    }
    expected = parent | STANDARD
    monkeypatch.setattr(sw_recovery, "_running_images", lambda _: set())
    monkeypatch.setattr(sw_recovery, "reset_connector_status", lambda: None)
    monkeypatch.setattr(
        sw_recovery,
        "read_connector_params",
        lambda: sw_recovery.ConnectorParams("space", "apps", "registry", "tenant"),
    )
    monkeypatch.setattr(
        sw_recovery, "resolve_install_root", lambda: Path("D:/installed")
    )
    environment = Mock(return_value=expected)
    monkeypatch.setattr(
        sw_install, "solidworks_launch_environment", environment, raising=False
    )
    launch = Mock()
    monkeypatch.setattr(sw_recovery.subprocess, "Popen", launch)
    monkeypatch.setattr(sw_recovery.os, "environ", parent)
    assert sw_recovery.start_solidworks() is True
    assert launch.call_args.kwargs["env"] is expected
    assert launch.call_args.kwargs["cwd"] == str(Path("D:/installed/win_b64/code/bin"))
    assert launch.call_args.kwargs["close_fds"] is True
    environment.assert_called_once_with(parent)
    assert parent == {
        "HARMONIC_COM_SEAT": "owned",
        "OTEL_SERVICE_NAME": "test",
        "PRIVATE_TOKEN": "private-value",
    }


def test_shortcut_launch_uses_hidden_bounded_argv_safe_child_with_original_shortcut(
    monkeypatch,
):
    shortcut = Path("D:/space & quote/SOLIDWORKS Design.lnk")
    parent = {"HARMONIC_COM_SEAT": "owned"}
    expected = parent | STANDARD
    monkeypatch.setattr(sw_install.os, "environ", parent)
    environment = Mock(return_value=expected)
    monkeypatch.setattr(
        sw_install, "solidworks_launch_environment", environment, raising=False
    )
    launch = Mock()
    monkeypatch.setattr(sw_install.subprocess, "run", launch)
    monkeypatch.setattr(
        sw_install.os,
        "startfile",
        lambda _: pytest.fail("must run in child"),
        raising=False,
    )
    sw_install.launch_via_platform_shortcut(shortcut)
    command = launch.call_args.args[0]
    assert command[0] == sys.executable
    assert command[-1] == str(shortcut)
    assert str(shortcut) not in command[command.index("-c") + 1]
    assert launch.call_args.kwargs["env"] is expected
    assert launch.call_args.kwargs["check"] is True
    assert launch.call_args.kwargs["timeout"] == 15
    assert launch.call_args.kwargs["creationflags"] == getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )
    environment.assert_called_once_with(parent)
    assert parent == {"HARMONIC_COM_SEAT": "owned"}


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.CalledProcessError(1, ["launcher"]),
        subprocess.TimeoutExpired(["launcher"], 15),
    ],
)
def test_shortcut_handoff_error_propagates_without_another_launch(monkeypatch, failure):
    monkeypatch.setattr(
        sw_install, "solidworks_launch_environment", lambda _: STANDARD, raising=False
    )
    launch = Mock(side_effect=failure)
    monkeypatch.setattr(sw_install.subprocess, "run", launch)
    monkeypatch.setattr(sw_install.os, "startfile", lambda _: None, raising=False)
    with pytest.raises(type(failure)):
        sw_install.launch_via_platform_shortcut(Path("D:/native.lnk"))
    assert launch.call_count == 1


def test_missing_standards_are_the_only_added_values_and_parent_is_unchanged(
    monkeypatch,
):
    parent = {
        "PATH": "task-path",
        "HARMONIC_COM_SEAT": "seat",
        "PRIVATE_TOKEN": "do-not-log",
    }
    original = dict(parent)
    monkeypatch.setattr(environment_module, "_native_architecture", lambda: 9)
    folders = Mock(
        side_effect=lambda identifier: (
            STANDARD["CommonProgramFiles"]
            if identifier == environment_module._COMMON_X64
            else STANDARD["CommonProgramFiles(x86)"]
        )
    )
    monkeypatch.setattr(environment_module, "_known_folder", folders)
    actual = environment_module.solidworks_launch_environment(parent)
    assert actual == original | STANDARD
    assert actual is not parent
    assert parent == original
    assert folders.call_count == 2  # CommonProgramFiles/W6432 share one lookup.


@pytest.mark.parametrize("existing", ["custom-value", ""])
def test_populated_case_insensitive_names_preserve_exact_values_without_native_reads(
    monkeypatch, existing
):
    parent = {name.swapcase(): existing for name in STANDARD} | {
        "TASK_VARIABLE": "retained"
    }
    monkeypatch.setattr(
        environment_module,
        "_native_architecture",
        lambda: pytest.fail("unneeded native architecture query"),
    )
    monkeypatch.setattr(
        environment_module,
        "_known_folder",
        lambda _: pytest.fail("unneeded native folder query"),
    )
    result = environment_module.solidworks_launch_environment(parent)
    assert result == parent
    assert result is not parent


def test_partial_environment_preserves_override_and_queries_only_missing_folder(
    monkeypatch,
):
    parent = {
        "COMMONPROGRAMFILES": "caller-override",
        "commonprogramw6432": "caller64",
        "processor_architecture": "caller-arch",
    }
    monkeypatch.setattr(environment_module, "_native_architecture", lambda: 9)
    folders = Mock(return_value=STANDARD["CommonProgramFiles(x86)"])
    monkeypatch.setattr(environment_module, "_known_folder", folders)
    assert environment_module.solidworks_launch_environment(parent) == parent | {
        "CommonProgramFiles(x86)": STANDARD["CommonProgramFiles(x86)"]
    }
    folders.assert_called_once_with(environment_module._COMMON_X86)


@pytest.mark.parametrize("architecture", [0, 5, 12, 65535])
def test_unknown_or_unverified_architecture_rejects_repair_before_folder_lookup(
    monkeypatch, architecture
):
    monkeypatch.setattr(
        environment_module, "_native_architecture", lambda: architecture
    )
    folders = Mock()
    monkeypatch.setattr(environment_module, "_known_folder", folders)
    with pytest.raises(OSError, match="native AMD64"):
        environment_module.solidworks_launch_environment({})
    folders.assert_not_called()


def test_failed_native_directory_lookup_does_not_change_parent(monkeypatch):
    parent = {"TASK_VARIABLE": "retained"}
    monkeypatch.setattr(environment_module, "_native_architecture", lambda: 9)
    monkeypatch.setattr(
        environment_module,
        "_known_folder",
        Mock(side_effect=OSError("native lookup failed")),
    )
    with pytest.raises(OSError, match="native lookup failed"):
        environment_module.solidworks_launch_environment(parent)
    assert parent == {"TASK_VARIABLE": "retained"}


@pytest.mark.skipif(
    os.name != "nt", reason="native Windows folder and harmless process receipt"
)
def test_native_child_receives_only_repaired_standards_and_inherited_task_context(
    monkeypatch,
):
    original = dict(os.environ)
    standard_keys = {key.casefold() for key in STANDARD}
    parent = {
        key: value
        for key, value in original.items()
        if key.casefold() not in standard_keys
    }
    parent["HARMONIC_COM_SEAT"] = "harmless-child-test"
    parent["PRIVATE_TEST_SENTINEL"] = "never-print-this"
    sent = environment_module.solidworks_launch_environment(parent)
    receipt = {}
    real_run = subprocess.run

    def harmless_child(command, **kwargs):
        # Execute the production launcher payload in a real Python child, but
        # substitute its final OS shell action. This never starts an application.
        child = list(command)
        index = child.index("-c") + 1
        prefix = (
            "import os, sys, json; "
            "os.startfile = lambda path: print(json.dumps({"
            "'shortcut': path, 'standards': {key: os.environ.get(key) for key in "
            + repr(tuple(STANDARD))
            + "}, 'task': os.environ.get('HARMONIC_COM_SEAT'), "
            "'private_retained': os.environ.get('PRIVATE_TEST_SENTINEL') == 'never-print-this'})); "
        )
        child[index] = prefix + child[index]
        observed = real_run(child, **kwargs)
        receipt.update(json.loads(observed.stdout))
        assert b"never-print-this" not in observed.stdout + observed.stderr
        return observed

    monkeypatch.setattr(sw_install.os, "environ", parent)
    monkeypatch.setattr(sw_install.subprocess, "run", harmless_child)
    shortcut = Path("D:/never-launched & literal/native.lnk")
    sw_install.launch_via_platform_shortcut(shortcut)
    assert receipt["shortcut"] == str(shortcut)
    assert receipt["standards"] == {key: sent[key] for key in STANDARD}
    assert receipt["task"] == "harmless-child-test"
    assert receipt["private_retained"] is True
    assert all(key.casefold() not in standard_keys for key in parent)
    assert parent["PRIVATE_TEST_SENTINEL"] == "never-print-this"


@pytest.mark.parametrize(
    "case", ["success", "hresult", "null", "relative", "rooted", "missing_directory"]
)
def test_known_folder_releases_native_output_on_every_path(monkeypatch, case):
    values = {"relative": "relative/path", "rooted": "\\rooted-no-drive"}
    allocation = ctypes.create_unicode_buffer(
        values.get(case, "D:\\Programs\\Common Files")
    )
    pointer = None if case == "null" else ctypes.cast(allocation, ctypes.c_void_p).value
    release = Mock()

    def query(identifier, flags, token, output):
        assert flags == 0 and token is None
        assert (
            bytes(identifier._obj)
            == environment_module.UUID(environment_module._COMMON_X64).bytes_le
        )
        output._obj.value = pointer
        return -2147467259 if case == "hresult" else 0

    folder = Mock(side_effect=query)
    libraries = {
        "shell32": Mock(SHGetKnownFolderPath=folder),
        "ole32": Mock(CoTaskMemFree=release),
    }
    monkeypatch.setattr(
        environment_module.ctypes, "WinDLL", libraries.__getitem__, raising=False
    )
    monkeypatch.setattr(
        environment_module.os.path, "isdir", lambda _: case != "missing_directory"
    )
    if case == "success":
        assert (
            environment_module._known_folder(environment_module._COMMON_X64)
            == allocation.value
        )
    if case != "success":
        with pytest.raises(OSError, match="lookup"):
            environment_module._known_folder(environment_module._COMMON_X64)
    release.assert_called_once()
    assert release.call_args.args[0].value == pointer


@pytest.mark.parametrize("path", ["connector", "shortcut"])
def test_environment_resolution_failure_prevents_either_launch(monkeypatch, path):
    monkeypatch.setattr(
        sw_install,
        "solidworks_launch_environment",
        Mock(side_effect=OSError("native environment unavailable")),
    )
    process, shell = Mock(), Mock()
    monkeypatch.setattr(sw_install.subprocess, "run", shell)
    monkeypatch.setattr(sw_recovery.subprocess, "Popen", process)
    monkeypatch.setattr(sw_recovery, "_running_images", lambda _: set())
    monkeypatch.setattr(sw_recovery, "reset_connector_status", lambda: None)
    monkeypatch.setattr(
        sw_recovery,
        "read_connector_params",
        lambda: sw_recovery.ConnectorParams("space", "apps", "registry", "tenant"),
    )
    monkeypatch.setattr(
        sw_recovery, "resolve_install_root", lambda: Path("D:/installed")
    )
    with pytest.raises(OSError, match="native environment unavailable"):
        if path == "connector":
            sw_recovery.start_solidworks()
        if path == "shortcut":
            sw_install.launch_via_platform_shortcut(Path("D:/native.lnk"))
    process.assert_not_called()
    shell.assert_not_called()
