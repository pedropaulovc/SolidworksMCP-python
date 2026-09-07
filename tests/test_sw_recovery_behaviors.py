"""Recovery orchestration contracts; every OS mutation is replaced before use."""

from contextlib import nullcontext
from types import SimpleNamespace as NS
from unittest.mock import Mock, call

import pytest

from solidworks_mcp.adapters import sw_recovery as r


@pytest.fixture(autouse=True)
def forbid_native_side_effects(monkeypatch):
    """Accidental launch/kill/registry access fails rather than reaching the host."""
    monkeypatch.setattr(r, "os", NS(name="nt", environ={}))
    monkeypatch.setattr(r, "winreg", None)
    monkeypatch.setattr(
        r,
        "subprocess",
        NS(
            run=Mock(side_effect=AssertionError("unmocked process operation")),
            Popen=Mock(side_effect=AssertionError("unmocked launch")),
            SubprocessError=RuntimeError,
        ),
    )
    monkeypatch.setattr(
        r,
        "time",
        NS(
            monotonic=Mock(side_effect=AssertionError("unmocked clock")),
            sleep=Mock(side_effect=AssertionError("unmocked sleep")),
        ),
    )
    for name in (
        "resolve_com_server_path",
        "resolve_launch_strategy",
        "launch_via_platform_shortcut",
        "solidworks_launch_environment",
    ):
        monkeypatch.setattr(
            r.sw_install,
            name,
            Mock(side_effect=AssertionError("unmocked launch helper")),
        )


def registry(monkeypatch, *, rows=(), missing=False):
    """Expose only an in-memory registry key and a recorded close operation."""
    key = object()
    values = Mock(side_effect=[*rows, OSError("end")])
    fake = NS(
        HKEY_CURRENT_USER="HKCU",
        KEY_SET_VALUE=2,
        REG_DWORD=4,
        OpenKey=Mock(side_effect=OSError("missing"))
        if missing
        else Mock(return_value=nullcontext(key)),
        EnumValue=values,
        SetValueEx=Mock(),
    )
    monkeypatch.setattr(r, "winreg", fake)
    return fake, key


@pytest.mark.parametrize("state", ["present", "missing", "unavailable"])
def test_registry_inventory_returns_actual_values_and_stops_at_end(monkeypatch, state):
    if state == "unavailable":
        assert r._read_key_values("key") == {}
        return
    fake, key = registry(
        monkeypatch,
        rows=[("Loaded", 2, 4), ("Tenant", "tenant", 1)],
        missing=state == "missing",
    )
    assert r._read_key_values("key") == (
        {"Loaded": 2, "Tenant": "tenant"} if state == "present" else {}
    )
    fake.OpenKey.assert_called_once_with("HKCU", "key")
    if state == "present":
        assert fake.EnumValue.call_args_list == [
            call(key, 0),
            call(key, 1),
            call(key, 2),
        ]


@pytest.mark.parametrize("style", ["canonical", "aliases", "incomplete"])
def test_connector_parameters_use_registry_fields_and_required_tenant(
    monkeypatch, style
):
    values = {
        "SpaceURL": " https://space ",
        "MyAppsURL": "https://apps",
        "RegistryURL": "https://registry",
        "TenantId": " tenant ",
    }
    if style == "aliases":
        values["Address"] = values.pop("SpaceURL")
        values["Tenant"] = values.pop("TenantId")
    if style == "incomplete":
        values.pop("TenantId")
    read = Mock(return_value=values)
    monkeypatch.setattr(r, "_read_key_values", read)
    result = r.read_connector_params()
    assert result == (
        None
        if style == "incomplete"
        else r.ConnectorParams(
            "https://space", "https://apps", "https://registry", "tenant"
        )
    )
    read.assert_called_once_with(r._SERVERS_KEY)


@pytest.mark.parametrize("state", ["present", "missing", "unavailable"])
def test_reset_touches_only_two_session_health_values(monkeypatch, state):
    if state == "unavailable":
        assert r.reset_connector_status() is None
        return
    fake, key = registry(monkeypatch, missing=state == "missing")
    r.reset_connector_status()
    if state == "missing":
        fake.SetValueEx.assert_not_called()
        return
    fake.OpenKey.assert_called_once_with("HKCU", r._LAST_RUN_KEY, 0, 2)
    assert fake.SetValueEx.call_args_list == [
        call(key, "CONNECTED_LOAD_STATUS", 0, 4, 0),
        call(key, "SOLIDWORKS_ISCONNECTED", 0, 4, 0),
    ]


@pytest.mark.parametrize(
    "status",
    [
        {"CONNECTED_LOAD_STATUS": "bad"},
        {"SOLIDWORKS_ISCONNECTED": None},
        {"CONNECTED_LOAD_STATUS": 2, "SOLIDWORKS_ISCONNECTED": 0},
    ],
)
def test_invalid_or_partial_connector_status_never_reports_ready(monkeypatch, status):
    monkeypatch.setattr(r, "_running_images", lambda _: {r.SW_MAIN_PROCESS})
    monkeypatch.setattr(r, "read_last_run_status", lambda: status)
    assert r.is_connector_loaded() is False


def test_tasklist_filters_requested_image_names_case_insensitively(monkeypatch):
    run = Mock(return_value=NS(stdout='"SLDWORKS.EXE","12"\n"unrelated.exe","7"'))
    monkeypatch.setattr(r.subprocess, "run", run)
    assert r._running_images(("sldworks.exe", "CATSTART.exe")) == {"sldworks.exe"}
    assert run.call_args.args == (["tasklist", "/NH", "/FO", "CSV"],)
    assert run.call_args.kwargs["timeout"] == 15


@pytest.mark.parametrize("tree", [False, True])
def test_taskkill_uses_explicit_image_and_optional_child_tree(monkeypatch, tree):
    run = Mock()
    monkeypatch.setattr(r.subprocess, "run", run)
    r._taskkill("owned.exe", tree=tree)
    assert run.call_args.args == (
        ["taskkill", "/F", "/IM", "owned.exe", *(["/T"] if tree else [])],
    )
    assert run.call_args.kwargs["timeout"] == 30


def test_kill_connectors_never_targets_persistent_platform_processes(monkeypatch):
    running = {r.CONNECTOR_AGENTS[0], r.CONNECTOR_AGENTS[-1]}
    scan, kill = Mock(return_value=running), Mock()
    monkeypatch.setattr(r, "_running_images", scan)
    monkeypatch.setattr(r, "_taskkill", kill)
    assert r.kill_connector_processes() == running
    scan.assert_called_once_with(r.CONNECTOR_AGENTS)
    assert {entry.args[0] for entry in kill.call_args_list} == running
    assert not running.intersection(r.PERSISTENT_PLATFORM_PROCESSES)


@pytest.mark.parametrize("state", ["already_stopped", "stopped", "timeout"])
def test_stop_waits_for_main_exit_without_killing_persistent_platform(
    monkeypatch, state
):
    scan = Mock(
        side_effect=[set(), set()]
        if state == "already_stopped"
        else [{r.SW_MAIN_PROCESS}, {r.SW_MAIN_PROCESS, r.CONNECTOR_AGENTS[0]}]
    )
    kill, wait = Mock(), Mock(return_value=state != "timeout")
    monkeypatch.setattr(r, "_running_images", scan)
    monkeypatch.setattr(r, "_taskkill", kill)
    monkeypatch.setattr(r, "_wait_gone", wait)
    assert r.stop_solidworks(timeout=17) is (state != "timeout")
    if state == "already_stopped":
        kill.assert_not_called()
        wait.assert_not_called()
        return
    assert kill.call_args_list == [
        call(r.SW_MAIN_PROCESS, tree=True),
        call(r.CONNECTOR_AGENTS[0]),
    ]
    wait.assert_called_once_with(r.SW_MAIN_PROCESS, 17)


@pytest.mark.parametrize("state", ["gone", "timeout"])
def test_wait_gone_checks_liveness_at_deadline(monkeypatch, state):
    monkeypatch.setattr(r.time, "monotonic", Mock(side_effect=[0.0, 0.0, 1.0]))
    monkeypatch.setattr(r.time, "sleep", Mock())
    scan = Mock(return_value=set() if state == "gone" else {"owned.exe"})
    monkeypatch.setattr(r, "_running_images", scan)
    assert r._wait_gone("owned.exe", 1.0) is (state == "gone")
    assert scan.call_count == (1 if state == "gone" else 2)


@pytest.mark.parametrize("state", ["loaded", "wedge", "timeout"])
def test_wait_connected_distinguishes_loaded_wedge_and_timeout(monkeypatch, state):
    monkeypatch.setattr(r.time, "monotonic", Mock(side_effect=[0.0, 0.0, 2.0]))
    monkeypatch.setattr(r.time, "sleep", Mock())
    monkeypatch.setattr(r, "is_dotnet_splash_wedged", lambda: state == "wedge")
    loaded = Mock(return_value=state == "loaded")
    monkeypatch.setattr(r, "is_connector_loaded", loaded)
    assert r.wait_until_connected(timeout=1.0) is (state == "loaded")
    assert loaded.call_count == (0 if state == "wedge" else 1)


@pytest.mark.parametrize(
    "state",
    ["ready", "stop_failed", "launch_failed", "recovered", "still_disconnected"],
)
def test_recovery_stops_on_failure_and_returns_observed_final_state(monkeypatch, state):
    final = (
        r.SolidWorksState.CONNECTED
        if state in {"ready", "recovered"}
        else r.SolidWorksState.RUNNING_DISCONNECTED
    )
    detect = Mock(
        side_effect=[r.SolidWorksState.CONNECTED]
        if state == "ready"
        else [r.SolidWorksState.STARTING, final]
    )
    stop, start, wait = (
        Mock(return_value=state != "stop_failed"),
        Mock(return_value=state != "launch_failed"),
        Mock(),
    )
    for name, callback in [
        ("detect_state", detect),
        ("stop_solidworks", stop),
        ("start_solidworks", start),
        ("wait_until_connected", wait),
    ]:
        monkeypatch.setattr(r, name, callback)
    assert r.recover_solidworks(stop_timeout=4, connect_timeout=9) is final
    assert stop.call_count == (0 if state == "ready" else 1)
    assert start.call_count == (0 if state in {"ready", "stop_failed"} else 1)
    if state in {"recovered", "still_disconnected"}:
        wait.assert_called_once_with(timeout=9)
    else:
        wait.assert_not_called()


@pytest.mark.parametrize("state", ["present", "missing", "no_registration"])
def test_install_root_requires_registered_executable_parent(
    tmp_path, monkeypatch, state
):
    executable = tmp_path / "version/SOLIDWORKS/sldworks.exe"
    if state == "present":
        executable.parent.mkdir(parents=True)
    monkeypatch.setattr(
        r.sw_install,
        "resolve_com_server_path",
        Mock(return_value=None if state == "no_registration" else str(executable)),
    )
    assert r.resolve_install_root() == (
        tmp_path / "version" if state == "present" else None
    )


@pytest.mark.parametrize(
    "command", ["status", "stop", "restart-connectors", "start", "recover"]
)
@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_cli_propagates_operation_outcome_without_extra_lifecycle_actions(
    monkeypatch, command, outcome, capsys
):
    operations = {
        "detect_state": Mock(return_value=r.SolidWorksState.STARTING),
        "is_dotnet_splash_wedged": Mock(return_value=False),
        "is_connector_loaded": Mock(return_value=False),
        "read_last_run_status": Mock(return_value={}),
        "stop_solidworks": Mock(return_value=outcome == "success"),
        "kill_connector_processes": Mock(return_value={"agent.exe"}),
        "start_solidworks": Mock(return_value=outcome == "success"),
        "recover_solidworks": Mock(
            return_value=r.SolidWorksState.CONNECTED
            if outcome == "success"
            else r.SolidWorksState.STARTING
        ),
    }
    for name, callback in operations.items():
        monkeypatch.setattr(r, name, callback)
    assert r._main([command]) == (
        1 if command in {"stop", "start", "recover"} and outcome == "failure" else 0
    )
    if command == "status":
        assert "starting" in capsys.readouterr().out
        operations["start_solidworks"].assert_not_called()
        operations["stop_solidworks"].assert_not_called()
