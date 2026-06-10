"""Direct branch coverage tests for adapters.solidworks.parametrics."""

from __future__ import annotations

from types import SimpleNamespace

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    CreateConfigurationParameters,
    CreateEquationCurveParameters,
    CreateEquationParameters,
    SetGlobalVariableParameters,
)
from solidworks_mcp.adapters.solidworks import parametrics


class _FakeAdapter:
    def __init__(self) -> None:
        self.currentModel = None
        self.currentSketchManager = None
        self._registered: list[tuple[str, object]] = []

    def _handle_com_operation(self, _name, callback):
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))

    def _attempt(self, callback, default=None):
        try:
            return callback()
        except Exception:
            return default

    def _register_sketch_entity(self, kind, segment):
        self._registered.append((kind, segment))
        return f"{kind}_{len(self._registered)}"


class _FakeEquationMgr:
    """Equation manager double with a list-backed equation table."""

    def __init__(self, equations: list[str] | None = None) -> None:
        self.equations = list(equations or [])
        self.add_calls: list[tuple] = []
        self.add2_calls: list[tuple] = []
        self.set_calls: list[tuple] = []
        self.put_calls: list[tuple] = []
        self.deleted: list[int] = []
        self.fail_add = False
        self.fail_add2 = False
        self.fail_set = False
        self.fail_put = False

    def GetCount(self):  # noqa: N802 — COM casing
        return len(self.equations)

    def Equation(self, index, equation=None):  # noqa: N802
        if equation is None:
            return self.equations[index]
        # Property put form (late-bound call with two arguments).
        self.put_calls.append((index, equation))
        if not self.fail_put:
            self.equations[index] = equation

    def Value(self, index):  # noqa: N802
        return 42.0

    def Add3(self, index, equation, solve, which, config_names):  # noqa: N802
        self.add_calls.append((index, equation, solve, which, config_names))
        if self.fail_add:
            return -1
        self.equations.append(equation)
        return len(self.equations) - 1

    def Add2(self, index, equation, solve):  # noqa: N802
        self.add2_calls.append((index, equation, solve))
        if self.fail_add2:
            return -1
        self.equations.append(equation)
        return len(self.equations) - 1

    def Delete(self, index):  # noqa: N802
        self.deleted.append(index)
        self.equations.pop(index)
        return 0

    def SetEquationAndConfigurationOption(  # noqa: N802
        self, index, equation, which, config_names
    ):
        self.set_calls.append((index, equation, which, config_names))
        if self.fail_set:
            return -1
        self.equations[index] = equation
        return index


def _model_with_equations(manager: _FakeEquationMgr, **extra):
    base = {
        "GetEquationMgr": lambda: manager,
        "ShowConfiguration2": lambda name: True,
    }
    base.update(extra)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# create_equation_driven_curve
# ---------------------------------------------------------------------------


def test_create_equation_curve_passes_expressions_verbatim() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentSketchManager = SimpleNamespace(
        CreateEquationSpline2=lambda *a: (
            calls.append(a) or SimpleNamespace(Name="curve")
        )
    )
    result = parametrics._create_equation_driven_curve_impl(
        adapter,
        CreateEquationCurveParameters(
            x_expression="0.05*cos(t)",
            y_expression="0.05*sin(t)",
            range_start="0",
            range_end="2*pi",
        ),
    )
    assert result.is_success
    assert result.data == "EquationCurve_1"
    assert calls == [
        (
            "0.05*cos(t)",
            "0.05*sin(t)",
            "",
            "0",
            "2*pi",
            False,
            0.0,
            0.0,
            0.0,
            True,
            True,
        )
    ]


def test_create_equation_curve_explicit_and_lock_flags() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentSketchManager = SimpleNamespace(
        CreateEquationSpline2=lambda *a: (
            calls.append(a) or SimpleNamespace(Name="curve")
        )
    )
    result = parametrics._create_equation_driven_curve_impl(
        adapter,
        CreateEquationCurveParameters(
            y_expression="sin(x)",
            range_start="0",
            range_end="6.28",
            lock_start=False,
            lock_end=False,
        ),
    )
    assert result.is_success
    assert calls[0][0] == ""  # explicit curve: empty x expression
    assert calls[0][-2:] == (False, False)


def test_create_equation_curve_requires_active_sketch() -> None:
    adapter = _FakeAdapter()
    result = parametrics._create_equation_driven_curve_impl(
        adapter,
        CreateEquationCurveParameters(
            y_expression="sin(x)", range_start="0", range_end="1"
        ),
    )
    assert result.is_error
    assert "No active sketch" in (result.error or "")


def test_create_equation_curve_null_segment_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentSketchManager = SimpleNamespace(
        CreateEquationSpline2=lambda *a: None
    )
    result = parametrics._create_equation_driven_curve_impl(
        adapter,
        CreateEquationCurveParameters(
            y_expression="sin(x)", range_start="0", range_end="1"
        ),
    )
    assert result.is_error
    assert "Failed to create equation-driven curve" in (result.error or "")


# ---------------------------------------------------------------------------
# set_global_variable / create_equation
# ---------------------------------------------------------------------------


def test_set_global_variable_adds_all_configurations() -> None:
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr()
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._set_global_variable_impl(
        adapter,
        SetGlobalVariableParameters(name="ToothCount", expression="24"),
    )
    assert result.is_success
    assert result.data == {
        "index": 0,
        "equation": '"ToothCount" = 24',
        "updated": False,
        "value": 42.0,
    }
    index, equation, solve, which, _names = manager.add_calls[0]
    assert (index, solve, which) == (-1, True, 2)  # append, solve, all configs
    assert equation == '"ToothCount" = 24'


def test_set_global_variable_updates_existing_row() -> None:
    """Unscoped updates edit in place via the Equation property put —
    SetEquationAndConfigurationOption returns -1 with swAllConfiguration and
    Delete + re-add fails while another equation references the variable."""
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr(['"Other" = 1', '"ToothCount" = 12'])
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._set_global_variable_impl(
        adapter,
        SetGlobalVariableParameters(name="ToothCount", expression="36"),
    )
    assert result.is_success
    assert result.data["updated"] is True
    assert result.data["index"] == 1
    assert manager.add_calls == []
    assert manager.set_calls == []
    assert manager.deleted == []
    assert manager.put_calls == [(1, '"ToothCount" = 36')]
    assert manager.equations[1] == '"ToothCount" = 36'


def test_set_global_variable_specific_configuration_scope() -> None:
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr()
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._set_global_variable_impl(
        adapter,
        SetGlobalVariableParameters(
            name="ToothCount", expression="24", configuration="T24"
        ),
    )
    assert result.is_success
    _idx, _eq, _solve, which, names = manager.add_calls[0]
    assert which == 3  # swSpecifyConfiguration
    # On non-Windows the bstr_array fallback is the plain list.
    assert list(getattr(names, "value", names)) == ["T24"]


def test_set_global_variable_falls_back_to_add2_on_single_config() -> None:
    """Add3 returns -1 on single-configuration models; Add2 must take over."""
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr()
    manager.fail_add = True
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._set_global_variable_impl(
        adapter, SetGlobalVariableParameters(name="X", expression="1")
    )
    assert result.is_success
    assert result.data["index"] == 0
    assert manager.add2_calls == [(-1, '"X" = 1', True)]


def test_set_global_variable_both_adds_failing_errors() -> None:
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr()
    manager.fail_add = True
    manager.fail_add2 = True
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._set_global_variable_impl(
        adapter, SetGlobalVariableParameters(name="X", expression="1")
    )
    assert result.is_error
    assert "Failed to add equation" in (result.error or "")


def test_set_global_variable_update_put_failure_errors() -> None:
    """A rejected property put leaves the old text in place; the read-back
    verification must surface that as an error instead of silent success."""
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr(['"X" = 1'])
    manager.fail_put = True
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._set_global_variable_impl(
        adapter, SetGlobalVariableParameters(name="X", expression="2")
    )
    assert result.is_error
    assert "Failed to update equation" in (result.error or "")
    assert manager.deleted == []  # never Delete + re-add: re-add can fail


def test_set_global_variable_updates_existing_row_per_configuration() -> None:
    """Configuration-scoped updates go through
    SetEquationAndConfigurationOption with swSpecifyConfiguration."""
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr(['"X" = 1'])
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._set_global_variable_impl(
        adapter,
        SetGlobalVariableParameters(name="X", expression="2", configuration="T2"),
    )
    assert result.is_success
    assert result.data["updated"] is True
    assert manager.put_calls == []
    index, equation, which, names = manager.set_calls[0]
    assert (index, equation, which) == (0, '"X" = 2', 3)
    assert list(getattr(names, "value", names)) == ["T2"]


def test_set_global_variable_per_configuration_set_rejected_errors() -> None:
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr(['"X" = 1'])
    manager.fail_set = True
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._set_global_variable_impl(
        adapter,
        SetGlobalVariableParameters(name="X", expression="2", configuration="T2"),
    )
    assert result.is_error
    assert "Failed to update equation for configuration 'T2'" in (result.error or "")
    assert manager.deleted == []


def test_set_global_variable_configuration_activation_failure_errors() -> None:
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr()
    adapter.currentModel = _model_with_equations(
        manager, ShowConfiguration2=lambda name: False
    )
    result = parametrics._set_global_variable_impl(
        adapter,
        SetGlobalVariableParameters(name="X", expression="1", configuration="T9"),
    )
    assert result.is_error
    assert "Failed to activate configuration: T9" in (result.error or "")


def test_set_global_variable_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = parametrics._set_global_variable_impl(
        adapter, SetGlobalVariableParameters(name="X", expression="1")
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_set_global_variable_no_equation_manager_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace()  # no GetEquationMgr
    result = parametrics._set_global_variable_impl(
        adapter, SetGlobalVariableParameters(name="X", expression="1")
    )
    assert result.is_error
    assert "Equation manager unavailable" in (result.error or "")


def test_create_equation_adds_dimension_equation() -> None:
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr()
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._create_equation_impl(
        adapter,
        CreateEquationParameters(equation='"D1@CirPattern1" = "ToothCount"'),
    )
    assert result.is_success
    assert result.data["equation"] == '"D1@CirPattern1" = "ToothCount"'
    assert result.data["updated"] is False


def test_create_equation_updates_matching_lhs() -> None:
    adapter = _FakeAdapter()
    manager = _FakeEquationMgr(['"D1@CirPattern1" = 6'])
    adapter.currentModel = _model_with_equations(manager)
    result = parametrics._create_equation_impl(
        adapter,
        CreateEquationParameters(equation='"D1@CirPattern1" = "ToothCount"'),
    )
    assert result.is_success
    assert result.data["updated"] is True
    assert manager.equations == ['"D1@CirPattern1" = "ToothCount"']


def test_create_equation_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = parametrics._create_equation_impl(
        adapter, CreateEquationParameters(equation='"A" = 1')
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


# ---------------------------------------------------------------------------
# create_configuration / set_active_configuration
# ---------------------------------------------------------------------------


def test_create_configuration_passes_arguments() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = SimpleNamespace(
        ConfigurationManager=SimpleNamespace(
            AddConfiguration2=lambda *a: calls.append(a) or SimpleNamespace(Name="T24")
        )
    )
    result = parametrics._create_configuration_impl(
        adapter,
        CreateConfigurationParameters(
            name="T24", comment="24 teeth", parent="Default", description="d"
        ),
    )
    assert result.is_success
    assert result.data == {"name": "T24", "parent": "Default"}
    assert calls == [("T24", "24 teeth", "", 0, "Default", "d", True)]


def test_create_configuration_null_result_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace(
        ConfigurationManager=SimpleNamespace(AddConfiguration2=lambda *a: None)
    )
    result = parametrics._create_configuration_impl(
        adapter, CreateConfigurationParameters(name="T24")
    )
    assert result.is_error
    assert "Failed to create configuration" in (result.error or "")


def test_create_configuration_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = parametrics._create_configuration_impl(
        adapter, CreateConfigurationParameters(name="T24")
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_set_active_configuration_shows_and_rebuilds() -> None:
    adapter = _FakeAdapter()
    shown: list[str] = []
    adapter.currentModel = SimpleNamespace(
        ShowConfiguration2=lambda name: shown.append(name) or True,
        EditRebuild3=lambda: True,
    )
    result = parametrics._set_active_configuration_impl(adapter, "T24")
    assert result.is_success
    assert result.data == {"name": "T24", "rebuilt": True}
    assert shown == ["T24"]


def test_set_active_configuration_already_active_short_circuits() -> None:
    """ShowConfiguration2 returns False for an already-active configuration,
    so the impl must not call it (and must still succeed) in that case."""
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace(
        ConfigurationManager=SimpleNamespace(
            ActiveConfiguration=SimpleNamespace(Name="T24")
        ),
        ShowConfiguration2=lambda name: False,  # would report failure if called
        EditRebuild3=lambda: True,
    )
    result = parametrics._set_active_configuration_impl(adapter, "T24")
    assert result.is_success
    assert result.data == {"name": "T24", "rebuilt": True}


def test_set_active_configuration_failure_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace(
        ShowConfiguration2=lambda name: False,
        EditRebuild3=lambda: True,
    )
    result = parametrics._set_active_configuration_impl(adapter, "Missing")
    assert result.is_error
    assert "Failed to activate configuration: Missing" in (result.error or "")


def test_set_active_configuration_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = parametrics._set_active_configuration_impl(adapter, "T24")
    assert result.is_error
    assert "No active model" in (result.error or "")
