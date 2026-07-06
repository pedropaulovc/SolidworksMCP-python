"""Direct branch coverage tests for adapters.solidworks.assembly."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    AddMateParameters,
    BeltChainParameters,
    ComponentCircularPatternParameters,
    ComponentLinearPatternParameters,
    ComponentRefParameters,
    InsertComponentParameters,
    MateEntityRef,
    MateRefParameters,
    MoveComponentParameters,
    ReplaceComponentParameters,
    RotateComponentParameters,
    SetComponentConfigurationParameters,
    SetComponentSolvingParameters,
    SuppressMateParameters,
)
from solidworks_mcp.adapters.mock_adapter import MockSolidWorksAdapter
from solidworks_mcp.adapters.solidworks import assembly as assembly_module


class _FakeAdapter:
    def __init__(self) -> None:
        self.currentModel = None
        self.swApp = None

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

    def _get_feature_id(self, _feature) -> str:
        return "feature-id"


class _FakeTransform:
    def __init__(self, array16) -> None:
        self.ArrayData = list(array16)


class _FakeComponent:
    def __init__(self, name="shaft-1", fixed=False, array16=None) -> None:
        self.Name2 = name
        self._fixed = fixed
        self.ReferencedConfiguration = "Default"
        self.applied_arrays: list[list[float]] = []
        self.solve_result = True
        self.Transform2 = _FakeTransform(
            array16 or [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0]
        )

    def IsFixed(self):  # noqa: N802
        return self._fixed

    def SetTransformAndSolve3(self, xform, this_configuration):  # noqa: N802
        if not self.solve_result:
            return False
        self.applied_arrays.append(list(xform.array16))
        self.Transform2 = _FakeTransform(xform.array16)
        return True


class _FakeMathUtility:
    def __init__(self) -> None:
        self.received: list[object] = []

    def CreateTransform(self, array16):  # noqa: N802
        # The impl wraps the doubles in VARIANT(VT_ARRAY|VT_R8) on Windows
        # (plain CreateTransform input silently yields an identity transform);
        # on non-Windows CI the double_array fallback is the bare list.
        self.received.append(array16)
        values = getattr(array16, "value", array16)
        return SimpleNamespace(array16=list(values))


class _FakeAssemblyModel:
    def __init__(self, components=None, select_result=True) -> None:
        self._components = dict(components or {})
        self.select_result = select_result
        self.selections: list[tuple[str, str, int]] = []
        self.fix_calls = 0
        self.unfix_calls = 0
        self.rebuilds = 0
        self.delete_result = True
        self.replace_calls: list[tuple] = []
        self.replace_result = True
        self.added: list[tuple] = []
        self.add_result_name = "inserted-1"
        self.Extension = SimpleNamespace(
            SelectByID2=self._select_by_id2,
            DeleteSelection2=self._delete_selection,
        )
        self.FeatureManager = SimpleNamespace()

    def GetTitle(self):  # noqa: N802
        return "frame.SLDASM"

    def ClearSelection2(self, _flag):  # noqa: N802
        return True

    def GetComponentByName(self, name):  # noqa: N802
        return self._components.get(name)

    def _select_by_id2(self, name, entity_type, x, y, z, append, mark, callout, option):
        self.selections.append((name, entity_type, mark))
        return self.select_result

    def _delete_selection(self, option):
        if self.delete_result:
            self._components.clear()
        return self.delete_result

    def FixComponent(self):  # noqa: N802
        self.fix_calls += 1
        for component in self._components.values():
            component._fixed = True

    def UnfixComponent(self):  # noqa: N802
        self.unfix_calls += 1
        for component in self._components.values():
            component._fixed = False

    def EditRebuild3(self):  # noqa: N802
        self.rebuilds += 1
        return True

    def ReplaceComponents2(  # noqa: N802
        self, file_name, config, replace_all, use_config_choice, reattach
    ):
        self.replace_calls.append(
            (file_name, config, replace_all, use_config_choice, reattach)
        )
        return self.replace_result

    def AddComponent5(  # noqa: N802
        self, path, config_option, new_config, use_config, existing_config, x, y, z
    ):
        self.added.append(
            (path, config_option, new_config, use_config, existing_config, x, y, z)
        )
        component = _FakeComponent(name=self.add_result_name)
        self._components[self.add_result_name] = component
        return component


def _adapter_with(model, components=None) -> _FakeAdapter:
    adapter = _FakeAdapter()
    adapter.currentModel = model
    adapter.swApp = SimpleNamespace(
        GetMathUtility=lambda: _FakeMathUtility(),
        DocumentVisible=lambda *args: None,
        OpenDoc6=lambda *args: SimpleNamespace(),
        GetOpenDocumentByName=lambda _path: None,
        ActivateDoc3=lambda *args: None,
    )
    return adapter


# ---------------------------------------------------------------------------
# Matrix helpers
# ---------------------------------------------------------------------------


def _assert_close(actual, expected, tol=1e-9) -> None:
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected, strict=True):
        assert abs(a - e) < tol, f"{actual} != {expected}"


def test_euler_zero_rotation_is_identity() -> None:
    rotation = assembly_module._euler_xyz_matrix([0, 0, 0])
    _assert_close(sum(rotation, []), [1, 0, 0, 0, 1, 0, 0, 0, 1])


def test_euler_z90_maps_x_axis_to_y_axis() -> None:
    rotation = assembly_module._euler_xyz_matrix([0, 0, 90])
    _assert_close(assembly_module._mat_vec(rotation, [1, 0, 0]), [0, 1, 0])


def test_axis_angle_matches_euler_for_z_rotation() -> None:
    euler = assembly_module._euler_xyz_matrix([0, 0, 37])
    rodrigues = assembly_module._axis_angle_matrix([0, 0, 2], 37)
    _assert_close(sum(euler, []), sum(rodrigues, []))


def test_axis_angle_zero_axis_raises() -> None:
    with pytest.raises(Exception, match="non-zero"):
        assembly_module._axis_angle_matrix([0, 0, 0], 45)


def test_transform_array_rows_are_axis_images() -> None:
    rotation = assembly_module._euler_xyz_matrix([0, 0, 90])
    array = assembly_module._transform_array(rotation, [0.1, 0.2, 0.3])
    # Row 0 = image of the component x-axis (rotated onto +Y)
    _assert_close(array[0:3], [0, 1, 0])
    _assert_close(array[3:6], [-1, 0, 0])
    _assert_close(array[6:9], [0, 0, 1])
    _assert_close(array[9:12], [0.1, 0.2, 0.3])
    assert array[12] == 1.0


def test_qualify_component_appends_stripped_title() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    assert assembly_module._qualify_component(adapter, "shaft-1") == "shaft-1@frame"
    assert assembly_module._qualify_component(adapter, "a-1@b") == "a-1@b"


# ---------------------------------------------------------------------------
# insert_component
# ---------------------------------------------------------------------------


def test_insert_component_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path="x.sldprt")
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_insert_component_empty_path_errors() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path="   ")
    )
    assert result.is_error
    assert "file_path is required" in (result.error or "")


def test_insert_component_bad_pose_errors() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path="x.sldprt", position=[1, 2])
    )
    assert result.is_error
    assert "position and rotation" in (result.error or "")


def test_insert_component_missing_file_errors(tmp_path) -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._insert_component_impl(
        adapter,
        InsertComponentParameters(file_path=str(tmp_path / "missing.sldprt")),
    )
    assert result.is_error
    assert "not found" in (result.error or "")


def test_insert_component_success_preloads_and_positions(tmp_path) -> None:
    part = tmp_path / "shaft.sldprt"
    part.write_text("", encoding="utf-8")
    model = _FakeAssemblyModel()
    adapter = _adapter_with(model)
    opened: list[tuple] = []
    adapter.swApp.OpenDoc6 = lambda *args: opened.append(args) or SimpleNamespace()

    result = assembly_module._insert_component_impl(
        adapter,
        InsertComponentParameters(
            file_path=str(part),
            position=[10, 20, 30],
            rotation=[0, 0, 90],
            configuration="T24",
        ),
    )

    assert result.is_success
    # Preloaded as a part (doc type 1)
    assert opened[0][1] == 1
    # AddComponent5 with the explicit configuration
    path, config_option, _, use_config, existing_config, x, y, z = model.added[0]
    assert path.lower().endswith("shaft.sldprt")
    assert config_option == 0
    assert use_config is True
    assert existing_config == "T24"
    assert (x, y, z) == (0.0, 0.0, 0.0)
    # Exact transform applied: translation in metres, Z-rotation rows
    component = model._components["inserted-1"]
    applied = component.applied_arrays[0]
    _assert_close(applied[0:3], [0, 1, 0])
    _assert_close(applied[9:12], [0.01, 0.02, 0.03])
    assert result.data["name"] == "inserted-1"
    assert result.data["position"] == [10.0, 20.0, 30.0]
    assert model.rebuilds >= 1


def test_insert_component_preloads_hidden_then_restores_visibility(tmp_path) -> None:
    part = tmp_path / "shaft.sldprt"
    part.write_text("", encoding="utf-8")
    adapter = _adapter_with(_FakeAssemblyModel())
    events: list[tuple] = []
    adapter.swApp.DocumentVisible = lambda visible, doc_type: events.append(
        ("visible", visible, doc_type)
    )
    adapter.swApp.OpenDoc6 = lambda *args: (
        events.append(("open", args[1])) or (SimpleNamespace())
    )

    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path=str(part))
    )

    assert result.is_success
    # The part is hidden (False) before the open and restored (True) after,
    # so the load never spins up the part's SceneGraph display buffers.
    assert events == [
        ("visible", False, 1),
        ("open", 1),
        ("visible", True, 1),
    ]


def test_insert_component_restores_visibility_on_preload_failure(tmp_path) -> None:
    part = tmp_path / "shaft.sldprt"
    part.write_text("", encoding="utf-8")
    adapter = _adapter_with(_FakeAssemblyModel())
    restored: list[bool] = []
    adapter.swApp.DocumentVisible = lambda visible, doc_type: restored.append(visible)
    adapter.swApp.OpenDoc6 = lambda *args: None
    adapter.swApp.GetOpenDocumentByName = lambda _path: None

    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path=str(part))
    )

    assert result.is_error
    # Visibility is restored to True even though the load failed.
    assert restored == [False, True]


def test_insert_component_unsupported_extension_errors(tmp_path) -> None:
    bad = tmp_path / "drawing.slddrw"
    bad.write_text("", encoding="utf-8")
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path=str(bad))
    )
    assert result.is_error
    assert "Unsupported component file type" in (result.error or "")


def test_insert_component_preload_failure_errors(tmp_path) -> None:
    part = tmp_path / "shaft.sldprt"
    part.write_text("", encoding="utf-8")
    adapter = _adapter_with(_FakeAssemblyModel())
    adapter.swApp.OpenDoc6 = lambda *args: None
    adapter.swApp.GetOpenDocumentByName = lambda _path: None

    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path=str(part))
    )
    assert result.is_error
    assert "Failed to preload" in (result.error or "")


def test_insert_component_null_component_errors(tmp_path) -> None:
    part = tmp_path / "shaft.sldprt"
    part.write_text("", encoding="utf-8")
    model = _FakeAssemblyModel()
    model.AddComponent5 = lambda *args: None
    adapter = _adapter_with(model)

    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path=str(part))
    )
    assert result.is_error
    assert "AddComponent5 failed" in (result.error or "")


def test_insert_component_fixed_component_is_floated_for_placement(tmp_path) -> None:
    """The auto-fixed first component is floated, placed and re-fixed."""
    part = tmp_path / "base.sldprt"
    part.write_text("", encoding="utf-8")
    model = _FakeAssemblyModel()

    def _add(*args):
        component = _FakeComponent(name="inserted-1", fixed=True)
        model._components["inserted-1"] = component
        return component

    model.AddComponent5 = _add
    adapter = _adapter_with(model)

    result = assembly_module._insert_component_impl(
        adapter, InsertComponentParameters(file_path=str(part), position=[5, 0, 0])
    )

    assert result.is_success
    assert model.unfix_calls == 1
    assert model.fix_calls == 1
    assert result.data["fixed"] is True


# ---------------------------------------------------------------------------
# remove_component
# ---------------------------------------------------------------------------


def test_remove_component_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = assembly_module._remove_component_impl(
        adapter, ComponentRefParameters(name="shaft-1")
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_remove_component_unknown_errors() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._remove_component_impl(
        adapter, ComponentRefParameters(name="ghost-1")
    )
    assert result.is_error
    assert "Component not found" in (result.error or "")


def test_remove_component_success_selects_and_deletes() -> None:
    model = _FakeAssemblyModel(components={"shaft-1": _FakeComponent()})
    adapter = _adapter_with(model)

    result = assembly_module._remove_component_impl(
        adapter, ComponentRefParameters(name="shaft-1")
    )

    assert result.is_success
    assert ("shaft-1@frame", "COMPONENT", 0) in model.selections
    assert result.data == {"name": "shaft-1", "removed": True}


def test_remove_component_still_present_errors() -> None:
    model = _FakeAssemblyModel(components={"shaft-1": _FakeComponent()})
    model.delete_result = False
    model.EditDelete = lambda: None
    adapter = _adapter_with(model)

    result = assembly_module._remove_component_impl(
        adapter, ComponentRefParameters(name="shaft-1")
    )
    assert result.is_error
    assert "still present" in (result.error or "")


# ---------------------------------------------------------------------------
# replace_component
# ---------------------------------------------------------------------------


def test_replace_component_success_uses_manual_config(tmp_path) -> None:
    replacement = tmp_path / "gear-24t.sldprt"
    replacement.write_text("", encoding="utf-8")
    model = _FakeAssemblyModel(components={"gear-12t-1": _FakeComponent("gear-12t-1")})
    adapter = _adapter_with(model)

    result = assembly_module._replace_component_impl(
        adapter,
        ReplaceComponentParameters(
            name="gear-12t-1",
            file_path=str(replacement),
            configuration="T24",
            replace_all=True,
        ),
    )

    assert result.is_success
    file_name, config, replace_all, choice, reattach = model.replace_calls[0]
    assert file_name.lower().endswith("gear-24t.sldprt")
    assert config == "T24"
    assert replace_all is True
    assert choice == assembly_module._REPLACE_CONFIG_MANUALLY_SELECT
    assert reattach is True


def test_replace_component_default_config_matches_name(tmp_path) -> None:
    replacement = tmp_path / "b.sldprt"
    replacement.write_text("", encoding="utf-8")
    model = _FakeAssemblyModel(components={"a-1": _FakeComponent("a-1")})
    adapter = _adapter_with(model)

    result = assembly_module._replace_component_impl(
        adapter, ReplaceComponentParameters(name="a-1", file_path=str(replacement))
    )

    assert result.is_success
    assert model.replace_calls[0][3] == assembly_module._REPLACE_CONFIG_MATCH_NAME


def test_replace_component_api_failure_errors(tmp_path) -> None:
    replacement = tmp_path / "b.sldprt"
    replacement.write_text("", encoding="utf-8")
    model = _FakeAssemblyModel(components={"a-1": _FakeComponent("a-1")})
    model.replace_result = False
    adapter = _adapter_with(model)

    result = assembly_module._replace_component_impl(
        adapter, ReplaceComponentParameters(name="a-1", file_path=str(replacement))
    )
    assert result.is_error
    assert "ReplaceComponents2 failed" in (result.error or "")


# ---------------------------------------------------------------------------
# move_component / rotate_component
# ---------------------------------------------------------------------------


def test_move_component_absolute_preserves_rotation() -> None:
    rotated = assembly_module._transform_array(
        assembly_module._euler_xyz_matrix([0, 0, 90]), [0.001, 0.0, 0.0]
    )
    component = _FakeComponent(array16=rotated)
    model = _FakeAssemblyModel(components={"shaft-1": component})
    adapter = _adapter_with(model)

    result = assembly_module._move_component_impl(
        adapter, MoveComponentParameters(name="shaft-1", position=[10, 20, 30])
    )

    assert result.is_success
    applied = component.applied_arrays[0]
    _assert_close(applied[0:3], [0, 1, 0])  # rotation untouched
    _assert_close(applied[9:12], [0.01, 0.02, 0.03])
    _assert_close(result.data["position"], [10, 20, 30])


def test_move_component_relative_adds_delta() -> None:
    component = _FakeComponent(
        array16=[1, 0, 0, 0, 1, 0, 0, 0, 1, 0.01, 0.0, 0.0, 1, 0, 0, 0]
    )
    model = _FakeAssemblyModel(components={"shaft-1": component})
    adapter = _adapter_with(model)

    result = assembly_module._move_component_impl(
        adapter,
        MoveComponentParameters(name="shaft-1", position=[5, 0, -2], relative=True),
    )

    assert result.is_success
    _assert_close(result.data["position"], [15, 0, -2])


def test_create_math_transform_marshals_vt_r8_double_array() -> None:
    """CreateTransform input must be VT_ARRAY|VT_R8 — a plain list marshals
    as VT_ARRAY|VT_VARIANT, which SolidWorks silently turns into an identity
    transform (components never move while every call reports success)."""
    utility = _FakeMathUtility()
    adapter = _adapter_with(_FakeAssemblyModel())
    adapter.swApp.GetMathUtility = lambda: utility
    array16 = assembly_module._transform_array(
        assembly_module._euler_xyz_matrix([0, 0, 0]), [0.0, 0.08, 0.0]
    )

    xform = assembly_module._create_math_transform(adapter, array16)

    assert xform.array16 == array16
    (payload,) = utility.received
    try:
        import pythoncom
        from win32com.client import VARIANT
    except Exception:
        assert payload == array16  # non-Windows fallback is the bare list
        return
    assert isinstance(payload, VARIANT)
    assert payload.varianttype == pythoncom.VT_ARRAY | pythoncom.VT_R8
    assert list(payload.value) == array16


def test_move_component_reports_solver_adjusted_position() -> None:
    """The reported position is read back AFTER the mate solve, not the
    requested target — the solver may legitimately adjust it."""
    component = _FakeComponent()

    def _solve_snapping_y(xform, _this_configuration):
        snapped = list(xform.array16)
        snapped[10] = 0.0  # a mate holds the component at y = 0
        component.applied_arrays.append(snapped)
        component.Transform2 = _FakeTransform(snapped)
        return True

    component.SetTransformAndSolve3 = _solve_snapping_y
    model = _FakeAssemblyModel(components={"shaft-1": component})
    adapter = _adapter_with(model)

    result = assembly_module._move_component_impl(
        adapter, MoveComponentParameters(name="shaft-1", position=[10, 20, 30])
    )

    assert result.is_success
    _assert_close(result.data["position"], [10, 0, 30])


def test_move_component_solver_failure_errors() -> None:
    component = _FakeComponent()
    component.solve_result = False
    component.SetTransformAndSolve2 = lambda xform: False
    model = _FakeAssemblyModel(components={"shaft-1": component})
    adapter = _adapter_with(model)

    result = assembly_module._move_component_impl(
        adapter, MoveComponentParameters(name="shaft-1", position=[1, 1, 1])
    )
    assert result.is_error
    assert "Failed to set the transform" in (result.error or "")


def test_rotate_component_about_offset_axis() -> None:
    """90 deg about a Z axis through (100, 0, 0) mm moves the origin."""
    component = _FakeComponent()
    model = _FakeAssemblyModel(components={"shaft-1": component})
    adapter = _adapter_with(model)

    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(
            name="shaft-1",
            angle=90,
            axis_vector=[0, 0, 1],
            axis_point=[100, 0, 0],
        ),
    )

    assert result.is_success
    applied = component.applied_arrays[0]
    # Rotation rows: x-axis image now +Y
    _assert_close(applied[0:3], [0, 1, 0])
    # Origin (0,0,0) rotated about (0.1, 0, 0): -> (0.1, -0.1, 0) metres
    _assert_close(applied[9:12], [0.1, -0.1, 0.0])
    _assert_close(result.data["position"], [100, -100, 0])


def test_rotate_component_zero_axis_errors() -> None:
    model = _FakeAssemblyModel(components={"shaft-1": _FakeComponent()})
    adapter = _adapter_with(model)
    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(name="shaft-1", angle=10, axis_vector=[0, 0, 0]),
    )
    assert result.is_error
    assert "non-zero" in (result.error or "")


def test_rotate_component_unknown_mode_errors() -> None:
    model = _FakeAssemblyModel(components={"shaft-1": _FakeComponent()})
    adapter = _adapter_with(model)
    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(name="shaft-1", angle=10, mode="drag"),
    )
    assert result.is_error
    assert "'exact' or 'kinematic'" in (result.error or "")


def test_rotate_component_exact_reports_empty_propagated() -> None:
    model = _FakeAssemblyModel(components={"shaft-1": _FakeComponent()})
    adapter = _adapter_with(model)
    result = assembly_module._rotate_component_impl(
        adapter, RotateComponentParameters(name="shaft-1", angle=10)
    )
    assert result.is_success
    assert result.data["mode"] == "exact"
    assert result.data["propagated"] == []


# ---------------------------------------------------------------------------
# fix_component / float_component
# ---------------------------------------------------------------------------


def test_fix_component_success_verifies_state() -> None:
    component = _FakeComponent("base-1", fixed=False)
    model = _FakeAssemblyModel(components={"base-1": component})
    adapter = _adapter_with(model)

    result = assembly_module._set_component_fixed_impl(
        adapter, ComponentRefParameters(name="base-1"), fixed=True
    )

    assert result.is_success
    assert model.fix_calls == 1
    assert result.data == {"name": "base-1", "fixed": True}


def test_float_component_success_verifies_state() -> None:
    component = _FakeComponent("base-1", fixed=True)
    model = _FakeAssemblyModel(components={"base-1": component})
    adapter = _adapter_with(model)

    result = assembly_module._set_component_fixed_impl(
        adapter, ComponentRefParameters(name="base-1"), fixed=False
    )

    assert result.is_success
    assert model.unfix_calls == 1
    assert result.data == {"name": "base-1", "fixed": False}


def test_fix_component_state_not_applied_errors() -> None:
    component = _FakeComponent("base-1", fixed=False)
    model = _FakeAssemblyModel(components={"base-1": component})
    model.FixComponent = lambda: None  # API silently does nothing
    adapter = _adapter_with(model)

    result = assembly_module._set_component_fixed_impl(
        adapter, ComponentRefParameters(name="base-1"), fixed=True
    )
    assert result.is_error
    assert "did not become fixed" in (result.error or "")


def test_fix_component_selection_failure_errors() -> None:
    model = _FakeAssemblyModel(
        components={"base-1": _FakeComponent()}, select_result=False
    )
    adapter = _adapter_with(model)

    result = assembly_module._set_component_fixed_impl(
        adapter, ComponentRefParameters(name="base-1"), fixed=True
    )
    assert result.is_error
    assert "Failed to select component" in (result.error or "")


# ---------------------------------------------------------------------------
# pattern_components_linear / pattern_components_circular
# ---------------------------------------------------------------------------


def _pattern_model(components, feature) -> _FakeAssemblyModel:
    model = _FakeAssemblyModel(components=components)
    model.pattern_calls = []

    def _linear(*args):
        model.pattern_calls.append(("linear", args))
        return feature

    def _circular(*args):
        model.pattern_calls.append(("circular", args))
        return feature

    named = SimpleNamespace(Select2=lambda append, mark: True)
    model.FeatureByName = lambda name: named if name == "Axis1" else None
    model.FeatureManager = SimpleNamespace(
        FeatureLinearPattern5=_linear,
        FeatureCircularPattern5=_circular,
    )
    return model


def test_pattern_linear_requires_direction() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._pattern_components_linear_impl(
        adapter,
        ComponentLinearPatternParameters(components=["a-1"], count=5, spacing=10.0),
    )
    assert result.is_error
    assert "direction_name or direction_point" in (result.error or "")


def test_pattern_linear_success_marks_and_units() -> None:
    feature = SimpleNamespace(Name="LocalLPattern1")
    model = _pattern_model({"rocker-1": _FakeComponent("rocker-1")}, feature)
    adapter = _adapter_with(model)

    result = assembly_module._pattern_components_linear_impl(
        adapter,
        ComponentLinearPatternParameters(
            components=["rocker-1"],
            count=20,
            spacing=15.875,
            direction_name="Axis1",
        ),
    )

    assert result.is_success
    # Component selected under mark 1 (assembly marks are swapped vs parts)
    assert ("rocker-1@frame", "COMPONENT", 1) in model.selections
    kind, args = model.pattern_calls[0]
    assert kind == "linear"
    assert args[0] == 20
    assert abs(args[1] - 0.015875) < 1e-12  # spacing in metres
    assert result.data.type == "LocalLinearPattern"
    assert result.data.parameters["direction_entity"] == "FEATURE"


def test_pattern_linear_component_selection_failure_errors() -> None:
    feature = SimpleNamespace(Name="LocalLPattern1")
    model = _pattern_model({"rocker-1": _FakeComponent("rocker-1")}, feature)
    model.select_result = False
    adapter = _adapter_with(model)

    result = assembly_module._pattern_components_linear_impl(
        adapter,
        ComponentLinearPatternParameters(
            components=["rocker-1"], count=3, spacing=5.0, direction_name="Axis1"
        ),
    )
    assert result.is_error
    assert "Failed to select component to pattern" in (result.error or "")


def test_pattern_circular_requires_axis() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._pattern_components_circular_impl(
        adapter,
        ComponentCircularPatternParameters(components=["a-1"], count=8),
    )
    assert result.is_error
    assert "axis_name or axis_point" in (result.error or "")


def test_pattern_circular_success_by_axis_name() -> None:
    feature = SimpleNamespace(Name="LocalCirPattern1")
    model = _pattern_model({"bolt-1": _FakeComponent("bolt-1")}, feature)
    adapter = _adapter_with(model)

    result = assembly_module._pattern_components_circular_impl(
        adapter,
        ComponentCircularPatternParameters(
            components=["bolt-1"], count=8, axis_name="Axis1"
        ),
    )

    assert result.is_success
    assert ("bolt-1@frame", "COMPONENT", 1) in model.selections
    kind, args = model.pattern_calls[0]
    assert kind == "circular"
    assert args[0] == 8
    assert abs(args[1] - math.radians(360.0)) < 1e-12
    assert result.data.type == "LocalCircularPattern"
    assert result.data.parameters["axis_entity"] == "AXIS"


def test_pattern_circular_unknown_axis_name_errors() -> None:
    feature = SimpleNamespace(Name="LocalCirPattern1")
    model = _pattern_model({"bolt-1": _FakeComponent("bolt-1")}, feature)
    adapter = _adapter_with(model)

    result = assembly_module._pattern_components_circular_impl(
        adapter,
        ComponentCircularPatternParameters(
            components=["bolt-1"], count=8, axis_name="Ghost"
        ),
    )
    assert result.is_error
    assert "Failed to select rotation axis by name" in (result.error or "")


def test_pattern_circular_null_feature_errors() -> None:
    model = _pattern_model({"bolt-1": _FakeComponent("bolt-1")}, None)
    adapter = _adapter_with(model)

    result = assembly_module._pattern_components_circular_impl(
        adapter,
        ComponentCircularPatternParameters(
            components=["bolt-1"], count=8, axis_name="Axis1"
        ),
    )
    assert result.is_error
    assert "Failed to create circular component pattern" in (result.error or "")


# ---------------------------------------------------------------------------
# Belt/Chain feature (swFmBeltAndChain)
# ---------------------------------------------------------------------------


class _BeltSurface:
    def __init__(self, axis=(0.0, 0.0, 1.0), radius=0.014, cylinder=True) -> None:
        self._axis = axis
        self._radius = radius
        self._cylinder = cylinder

    def IsCylinder(self):  # noqa: N802
        return self._cylinder

    @property
    def CylinderParams(self):  # noqa: N802
        ax, ay, az = self._axis
        return [0.0, 0.0, 0.0, ax, ay, az, self._radius]


class _BeltFace:
    def __init__(self, surface) -> None:
        self._surface = surface

    def GetSurface(self):  # noqa: N802
        return self._surface


class _BeltPulley:
    def __init__(self, name, faces) -> None:
        self.Name2 = name
        self._faces = faces

    def GetBody(self):  # noqa: N802
        return SimpleNamespace(GetFaces=lambda: self._faces)


def _belt_model(pulleys, feature, plane_name="Front Plane"):
    model = _FakeAssemblyModel(components=pulleys)
    ref_plane = SimpleNamespace(_kind="refplane")
    plane_feat = SimpleNamespace(GetSpecificFeature2=lambda: ref_plane)
    model.FeatureByName = lambda name: plane_feat if name == plane_name else None
    model.created_defs: list[int] = []
    model.created_features: list[Any] = []

    def _create_definition(feature_id):
        model.created_defs.append(feature_id)
        # A settable feature-data stand-in (early_bound passes it through since
        # it has no _oleobj_); attributes are captured for assertions.
        return SimpleNamespace()

    def _create_feature(data):
        model.created_features.append(data)
        # The real feature exposes the committed definition; the post-create
        # diameter enforce reads PulleyDiameters back through it.
        feature.GetDefinition = lambda: data
        return feature

    model.FeatureManager = SimpleNamespace(
        CreateDefinition=_create_definition,
        CreateFeature=_create_feature,
        GetCreateFeatureErrors=lambda: 0,
    )
    model.blank_sketch_calls = []
    model.BlankSketch = lambda: model.blank_sketch_calls.append(1)
    return model


def test_belt_requires_two_pulleys() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(pulley_components=["a-1"], pulley_diameters=[24.0]),
    )
    assert result.is_error
    assert "at least 2 pulley_components" in (result.error or "")


def test_belt_diameters_length_mismatch() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["a-1", "b-1"], pulley_diameters=[24.0]
        ),
    )
    assert result.is_error
    assert "pulley_diameters must match" in (result.error or "")


def test_belt_flip_sides_length_mismatch() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["a-1", "b-1"],
            pulley_diameters=[24.0, 48.0],
            flip_sides=[False],
        ),
    )
    assert result.is_error
    assert "flip_sides" in (result.error or "")


def test_belt_unknown_axis_errors() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["a-1", "b-1"],
            pulley_diameters=[24.0, 48.0],
            pulley_axis="w",
        ),
    )
    assert result.is_error
    assert "Unknown pulley_axis" in (result.error or "")


def test_belt_no_active_model_errors() -> None:
    adapter = _FakeAdapter()  # currentModel is None
    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["a-1", "b-1"], pulley_diameters=[24.0, 48.0]
        ),
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_belt_component_not_found_errors() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())  # no components
    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["ghost-1", "b-1"], pulley_diameters=[24.0, 48.0]
        ),
    )
    assert result.is_error
    assert "Pulley component not found" in (result.error or "")


def test_belt_no_axial_cylinder_errors() -> None:
    # Only a radial (X-axis) cylinder -> no Z-axis pulley face.
    radial = _BeltPulley("t12-1", [_BeltFace(_BeltSurface(axis=(1.0, 0.0, 0.0)))])
    axial = _BeltPulley("t24-1", [_BeltFace(_BeltSurface(axis=(0.0, 0.0, 1.0)))])
    model = _belt_model({"t12-1": radial, "t24-1": axial}, SimpleNamespace(Name="Belt1"))
    adapter = _adapter_with(model)
    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["t12-1", "t24-1"], pulley_diameters=[24.0, 48.0]
        ),
    )
    assert result.is_error
    assert "cylindrical face" in (result.error or "")


def test_belt_plane_not_found_errors() -> None:
    t12 = _BeltPulley("t12-1", [_BeltFace(_BeltSurface(radius=0.014))])
    t24 = _BeltPulley("t24-1", [_BeltFace(_BeltSurface(radius=0.026))])
    model = _belt_model({"t12-1": t12, "t24-1": t24}, SimpleNamespace(Name="Belt1"))
    adapter = _adapter_with(model)
    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["t12-1", "t24-1"],
            pulley_diameters=[24.0, 48.0],
            location_plane="Nonexistent Plane",
        ),
    )
    assert result.is_error
    assert "plane not found" in (result.error or "")


def test_belt_success_sets_faces_diameters_and_engages() -> None:
    # The larger-radius coaxial (Z) cylinder is the rim; a smaller bore cylinder
    # must be ignored so PulleyComponents carries the rim faces.
    t12 = _BeltPulley(
        "t12-1",
        [
            _BeltFace(_BeltSurface(radius=0.005)),  # bore
            _BeltFace(_BeltSurface(radius=0.014)),  # rim
        ],
    )
    t24 = _BeltPulley("t24-1", [_BeltFace(_BeltSurface(radius=0.026))])
    feature = SimpleNamespace(Name="Belt1")
    model = _belt_model({"t12-1": t12, "t24-1": t24}, feature)
    adapter = _adapter_with(model)

    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["t12-1", "t24-1"],
            pulley_diameters=[24.0, 48.0],
            engage_belt=True,
            create_belt_part=False,
        ),
    )

    assert result.is_success
    assert result.data.type == "BeltChain"
    assert result.data.parameters["pulleys"] == 2
    # CreateDefinition was called with the belt/chain enum, CreateFeature once.
    assert model.created_defs == [assembly_module._SW_FM_BELT_AND_CHAIN]
    assert len(model.created_features) == 1
    data = model.created_features[0]
    # The array helpers wrap in a VARIANT on Windows (pywin32) and fall back to a
    # plain list on non-Windows CI; unwrap ``.value`` to read either.
    def _seq(v):
        return list(getattr(v, "value", v))

    # Diameters were converted mm -> metres, same order as the pulleys.
    assert _seq(data.PulleyDiameters) == [0.024, 0.048]
    # Pulley members are the two rim FACES (not the components/bores).
    assert len(_seq(data.PulleyComponents)) == 2
    assert data.EngageBelt is True
    assert data.CreateBeltPart is False


def test_belt_blanks_generated_sketch() -> None:
    t12 = _BeltPulley("t12-1", [_BeltFace(_BeltSurface(radius=0.014))])
    t24 = _BeltPulley("t24-1", [_BeltFace(_BeltSurface(radius=0.026))])
    # The belt feature exposes a generated belt-path sketch as its sub-feature.
    sketch_sub = SimpleNamespace(
        GetTypeName2=lambda: "ProfileFeature",
        Name="Belt1Sketch",
        GetNextSubFeature=lambda: None,
    )
    feature = SimpleNamespace(
        Name="Belt1", GetFirstSubFeature=lambda: sketch_sub
    )
    model = _belt_model({"t12-1": t12, "t24-1": t24}, feature)
    adapter = _adapter_with(model)

    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["t12-1", "t24-1"],
            pulley_diameters=[24.0, 48.0],
            blank_sketch=True,
        ),
    )

    assert result.is_success
    # The generated sketch was selected (SKETCH mark 0) and blanked.
    assert ("Belt1Sketch", "SKETCH", 0) in model.selections
    assert model.blank_sketch_calls == [1]


def test_belt_skips_blank_when_disabled() -> None:
    t12 = _BeltPulley("t12-1", [_BeltFace(_BeltSurface(radius=0.014))])
    t24 = _BeltPulley("t24-1", [_BeltFace(_BeltSurface(radius=0.026))])
    sketch_sub = SimpleNamespace(
        GetTypeName2=lambda: "ProfileFeature",
        Name="Belt1Sketch",
        GetNextSubFeature=lambda: None,
    )
    feature = SimpleNamespace(
        Name="Belt1", GetFirstSubFeature=lambda: sketch_sub
    )
    model = _belt_model({"t12-1": t12, "t24-1": t24}, feature)
    adapter = _adapter_with(model)

    result = assembly_module._insert_belt_chain_impl(
        adapter,
        BeltChainParameters(
            pulley_components=["t12-1", "t24-1"],
            pulley_diameters=[24.0, 48.0],
            blank_sketch=False,
        ),
    )

    assert result.is_success
    assert model.blank_sketch_calls == []


# ---------------------------------------------------------------------------
# Mates (Phase 7B)
# ---------------------------------------------------------------------------


class _FakeMate:
    def __init__(self, name, type_name="MateCoincident", suppressed=False) -> None:
        self.Name = name
        self._type_name = type_name
        self._suppressed = suppressed
        self._next = None
        self.select_result = True
        self.suppression_calls: list[tuple[int, int]] = []
        self.suppression_applies = True
        self.definition = SimpleNamespace()
        self.mate_data: Any = None

    def GetDefinition(self):  # noqa: N802
        return self.definition

    def GetTypeName2(self):  # noqa: N802
        return self._type_name

    def GetNextSubFeature(self):  # noqa: N802
        return self._next

    def IsSuppressed(self):  # noqa: N802
        return self._suppressed

    def Select2(self, _append, _mark):  # noqa: N802
        return self.select_result

    def SetSuppression2(self, action, configuration_option, _config_names):  # noqa: N802
        self.suppression_calls.append((action, configuration_option))
        if self.suppression_applies:
            self._suppressed = action == 0
        return True


class _FakeMateData:
    """Stand-in for a typed ``CreateMateData`` feature-data object.

    Permissive by design: ``_create_standard_mate`` / ``_create_mechanical_mate``
    set whichever typed properties the mate kind needs (``EntitiesToMate`` /
    ``MateAlignment`` / ``Distance`` / ``FlipDimension`` / ``Angle`` /
    ``LockRotation`` / ``GearRatio*`` / ``Reverse`` / limits / ``Revolution*`` /
    ``Width*`` / ``Diameter*``); tests read them straight back off this object.
    ``ErrorStatus`` defaults to "no error" (1) and is overwritten by
    :meth:`_MateModel.CreateMate` when a failure is simulated.
    """

    def __init__(self, mate_type) -> None:
        self.mate_type = mate_type
        self.ErrorStatus = 1
        # Entity attachment.
        self.EntitiesToMate: Any = None
        self.WidthSelection: Any = None
        self.TabSelection: Any = None
        self.ConstraintType: Any = None
        # Shared / per-kind typed properties.
        self.MateAlignment: Any = None
        self.Distance: Any = None
        self.FlipDimension: Any = None
        self.Angle: Any = None
        self.IsAdvancedMate: Any = None
        self.MinimumDistance: Any = None
        self.MaximumDistance: Any = None
        self.MinimumAngle: Any = None
        self.MaximumAngle: Any = None
        self.LockRotation: Any = None
        self.GearRatioNumerator: Any = None
        self.GearRatioDenominator: Any = None
        self.Reverse: Any = None
        self.RevolutionType: Any = None
        self.RevolutionVal: Any = None
        self.DiameterType: Any = None
        self.DiameterVal: Any = None


class _FakeMateSelectionManager:
    """Stand-in for ``ISelectionMgr`` feeding ``EntitiesToMate`` harvest.

    ``_harvest_selected`` re-reads the pre-selected entities via
    ``GetSelectedObject6(index, -1)`` (1-based); return a distinct sentinel per
    index so the harvested list is non-empty and order-stable.
    """

    def GetSelectedObject6(self, index, mark):  # noqa: N802
        if index < 1:
            return None
        return SimpleNamespace(selected_index=index, mark=mark)


class _FakeMateGroup:
    def __init__(self, mates) -> None:
        self.mates = list(mates)
        self.Name = "Mates"

    def GetTypeName2(self):  # noqa: N802
        return "MateGroup"

    def GetFirstSubFeature(self):  # noqa: N802
        for mate, succ in zip(self.mates, self.mates[1:], strict=False):
            mate._next = succ
        if self.mates:
            self.mates[-1]._next = None
        return self.mates[0] if self.mates else None

    def GetNextFeature(self):  # noqa: N802
        return None


class _MateModel(_FakeAssemblyModel):
    def __init__(self, mates=(), select_result=True) -> None:
        super().__init__(select_result=select_result)
        self.mate_group = _FakeMateGroup(mates)
        self.FirstFeature = self.mate_group
        self.SelectionManager = _FakeMateSelectionManager()
        self.point_selections: list[tuple] = []
        self.add_mate_name = "Coincident1"
        # swAddMateError_e returned via CreateMateData(...).ErrorStatus; 1 = ok.
        self.add_mate_status = 1
        self._last_feature = None
        self.create_mate_data_calls: list[int] = []
        self.created_mate_data: list[_FakeMateData] = []

    def CreateMateData(self, mate_type):  # noqa: N802
        self.create_mate_data_calls.append(mate_type)
        data = _FakeMateData(mate_type)
        self.created_mate_data.append(data)
        return data

    def CreateMate(self, data):  # noqa: N802
        if self.add_mate_status != 1:
            data.ErrorStatus = self.add_mate_status
            return None
        mate = _FakeMate(self.add_mate_name)
        mate.mate_data = data
        self.mate_group.mates.append(mate)
        return mate

    def FeatureByName(self, name):  # noqa: N802
        mate = next((m for m in self.mate_group.mates if m.Name == name), None)
        self._last_feature = mate
        return mate

    def _select_by_id2(self, name, entity_type, x, y, z, append, mark, callout, option):
        self.point_selections.append((name, entity_type, x, y, z, mark))
        return super()._select_by_id2(
            name, entity_type, x, y, z, append, mark, callout, option
        )

    def _delete_selection(self, option):
        if not self.delete_result:
            return False
        if self._last_feature in self.mate_group.mates:
            self.mate_group.mates.remove(self._last_feature)
        return True


def _harvested(value) -> list:
    """Unwrap an ``EntitiesToMate`` value to a plain list.

    ``dispatch_array`` returns a ``VT_ARRAY | VT_DISPATCH`` VARIANT on Windows
    (where pywin32 is installed) and the bare list on CI; ``.value`` yields the
    underlying sequence in the VARIANT case (mirrors ``_FakeMathUtility``).
    """
    return list(getattr(value, "value", value))


def _two_entities() -> list[MateEntityRef]:
    return [
        MateEntityRef(entity_type="PLANE", name="Plane1@shaft-1"),
        MateEntityRef(entity_type="PLANE", name="Front Plane"),
    ]


def test_qualify_entity_name_appends_title_for_single_at() -> None:
    adapter = _adapter_with(_FakeAssemblyModel())
    qualify = assembly_module._qualify_entity_name
    assert qualify(adapter, "Plane1@shaft-1") == "Plane1@shaft-1@frame"
    assert qualify(adapter, "Front Plane") == "Front Plane"
    assert qualify(adapter, "Plane1@shaft-1@other") == "Plane1@shaft-1@other"


def test_add_mate_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="coincident", entities=_two_entities())
    )
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_add_mate_unknown_type_errors() -> None:
    adapter = _adapter_with(_MateModel())
    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="magnetic", entities=_two_entities())
    )
    assert result.is_error
    assert "Unknown mate_type" in (result.error or "")


def test_add_mate_unknown_alignment_errors() -> None:
    adapter = _adapter_with(_MateModel())
    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="coincident", entities=_two_entities(), alignment="flipped"
        ),
    )
    assert result.is_error
    assert "Unknown alignment" in (result.error or "")


def test_add_mate_entity_count_validation() -> None:
    adapter = _adapter_with(_MateModel())
    one = [MateEntityRef(entity_type="FACE", name="x@a-1")]
    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="coincident", entities=one)
    )
    assert result.is_error
    assert "at least 2 entities" in (result.error or "")

    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="width", entities=_two_entities())
    )
    assert result.is_error
    assert "at least 4 entities" in (result.error or "")


def test_add_mate_bad_limits_errors() -> None:
    adapter = _adapter_with(_MateModel())
    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="distance", entities=_two_entities(), distance_limits=[1.0]
        ),
    )
    assert result.is_error
    assert "distance_limits must be [min, max]" in (result.error or "")


def test_add_mate_concentric_success_selects_and_names() -> None:
    model = _MateModel()
    model.add_mate_name = "Concentric1"
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="concentric",
            entities=_two_entities(),
            alignment="anti_aligned",
            lock_rotation=True,
        ),
    )

    assert result.is_success
    # Names qualified and selected under the default standard mark 1
    assert ("Plane1@shaft-1@frame", "PLANE", 1) in model.selections
    assert ("Front Plane", "PLANE", 1) in model.selections
    assert model.create_mate_data_calls == [1]  # CreateMateData(swMateCONCENTRIC)
    data = model.created_mate_data[0]
    assert data.MateAlignment == 1  # anti_aligned
    assert data.LockRotation is True
    assert len(_harvested(data.EntitiesToMate)) == 2  # both entities harvested
    assert result.data == {
        "name": "Concentric1",
        "mate_type": "concentric",
        "alignment": "anti_aligned",
        "entities": 2,
    }
    assert model.rebuilds >= 1


def test_add_mate_width_uses_mark_16() -> None:
    model = _MateModel()
    model.add_mate_name = "Width1"
    adapter = _adapter_with(model)

    entities = [
        MateEntityRef(entity_type="FACE", name=f"face{i}@slide-1") for i in range(4)
    ]
    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="width", entities=entities)
    )

    assert result.is_success
    assert all(mark == 16 for (_, _, mark) in model.selections)
    assert model.create_mate_data_calls == [11]  # CreateMateData(swMateWIDTH)
    data = model.created_mate_data[0]
    assert len(_harvested(data.WidthSelection)) == 2  # first two are the width faces
    assert len(_harvested(data.TabSelection)) == 2  # remaining are the tab faces
    assert data.ConstraintType == 1  # swMateWidthConstraint_Centered


def test_add_mate_rack_pinion_uses_marks_64_and_128() -> None:
    # Rack-pinion needs DISTINCT marks per entity (rack 64, pinion 128); a single
    # shared default mark makes CreateMate reject the selection.
    model = _MateModel()
    model.add_mate_name = "RackPinion1"
    adapter = _adapter_with(model)

    entities = [
        MateEntityRef(entity_type="AXIS", name="Axis1@platen-1"),  # rack
        MateEntityRef(entity_type="AXIS", name="Axis1@pinion-1"),  # pinion
    ]
    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="rack_pinion",
            entities=entities,
            rack_travel_per_revolution=63.84,
        ),
    )

    assert result.is_success
    marks = [mark for (_, _, mark) in model.selections]
    assert marks == [64, 128]  # rack first (64), pinion second (128)
    assert model.create_mate_data_calls == [13]  # CreateMateData(swMateRACKPINION)
    data = model.created_mate_data[0]
    assert data.DiameterType == assembly_module._RACK_PINION_TRAVEL_PER_REVOLUTION
    assert abs(data.DiameterVal - 0.06384) < 1e-9  # travel in metres


def test_add_mate_rack_pinion_explicit_marks_win() -> None:
    # An explicit ref.mark overrides the rack/pinion default assignment.
    model = _MateModel()
    adapter = _adapter_with(model)
    entities = [
        MateEntityRef(entity_type="AXIS", name="Axis1@platen-1", mark=128),
        MateEntityRef(entity_type="AXIS", name="Axis1@pinion-1", mark=64),
    ]
    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="rack_pinion",
            entities=entities,
            pinion_pitch_diameter=81.28,
        ),
    )
    assert result.is_success
    assert [mark for (_, _, mark) in model.selections] == [128, 64]


def test_add_mate_distance_converts_units_and_limits() -> None:
    model = _MateModel()
    model.add_mate_name = "Distance1"
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="distance",
            entities=_two_entities(),
            distance=25.4,
            distance_limits=[10.0, 50.0],
            angle=90.0,
        ),
    )

    assert result.is_success
    assert model.create_mate_data_calls == [5]  # CreateMateData(swMateDISTANCE)
    data = model.created_mate_data[0]
    assert abs(data.Distance - 0.0254) < 1e-12  # distance in metres
    assert data.IsAdvancedMate is True  # limits promote to a LimitDistance mate
    assert abs(data.MinimumDistance - 0.010) < 1e-12  # lower limit in metres
    assert abs(data.MaximumDistance - 0.050) < 1e-12  # upper limit in metres
    assert data.FlipDimension is False  # positive offset, default side


def test_add_mate_by_point_converts_to_metres() -> None:
    model = _MateModel()
    adapter = _adapter_with(model)

    entities = [
        MateEntityRef(entity_type="FACE", point=[10.0, 20.0, 30.0]),
        MateEntityRef(entity_type="PLANE", name="Front Plane"),
    ]
    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="coincident", entities=entities)
    )

    assert result.is_success
    name, entity_type, x, y, z, mark = model.point_selections[0]
    assert (name, entity_type, mark) == ("", "FACE", 1)
    _assert_close([x, y, z], [0.01, 0.02, 0.03])


def test_add_mate_selection_failure_errors() -> None:
    model = _MateModel(select_result=False)
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="coincident", entities=_two_entities())
    )
    assert result.is_error
    assert "Failed to select mate entity 1" in (result.error or "")


def test_add_mate_error_status_reports_reason() -> None:
    # A failed CreateMate returns None and reports the reason via the mate-data
    # object's ErrorStatus (swAddMateError_e); 4 = incorrect selections.
    model = _MateModel()
    model.add_mate_status = 4
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="coincident", entities=_two_entities())
    )
    assert result.is_error
    assert "incorrect selections" in (result.error or "")


def test_list_mates_walks_mate_group() -> None:
    mates = [
        _FakeMate("Coincident1"),
        _FakeMate("Distance1", type_name="MateDistanceDim", suppressed=True),
    ]
    adapter = _adapter_with(_MateModel(mates=mates))

    result = assembly_module._list_mates_impl(adapter)

    assert result.is_success
    assert result.data == [
        {"name": "Coincident1", "type": "MateCoincident", "suppressed": False},
        {"name": "Distance1", "type": "MateDistanceDim", "suppressed": True},
    ]


def test_list_mates_no_model_errors() -> None:
    result = assembly_module._list_mates_impl(_FakeAdapter())
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_delete_mate_success_removes_feature() -> None:
    mate = _FakeMate("Coincident1")
    model = _MateModel(mates=[mate])
    adapter = _adapter_with(model)

    result = assembly_module._delete_mate_impl(
        adapter, MateRefParameters(name="Coincident1")
    )

    assert result.is_success
    assert result.data == {"name": "Coincident1", "removed": True}
    assert mate not in model.mate_group.mates


def test_delete_mate_unknown_errors() -> None:
    adapter = _adapter_with(_MateModel())
    result = assembly_module._delete_mate_impl(
        adapter, MateRefParameters(name="Ghost1")
    )
    assert result.is_error
    assert "Mate not found" in (result.error or "")


def test_delete_mate_still_present_errors() -> None:
    mate = _FakeMate("Coincident1")
    model = _MateModel(mates=[mate])
    model.delete_result = False
    model.EditDelete = lambda: None
    adapter = _adapter_with(model)

    result = assembly_module._delete_mate_impl(
        adapter, MateRefParameters(name="Coincident1")
    )
    assert result.is_error
    assert "still present" in (result.error or "")


def test_delete_mate_empty_name_errors() -> None:
    adapter = _adapter_with(_MateModel())
    result = assembly_module._delete_mate_impl(adapter, MateRefParameters(name="  "))
    assert result.is_error
    assert "name is required" in (result.error or "")


def test_suppress_mate_success_applies_all_configurations() -> None:
    mate = _FakeMate("Distance1")
    adapter = _adapter_with(_MateModel(mates=[mate]))

    result = assembly_module._suppress_mate_impl(
        adapter, SuppressMateParameters(name="Distance1", suppress=True)
    )

    assert result.is_success
    assert mate.suppression_calls == [(0, 2)]  # suppress, all configurations
    assert result.data == {
        "name": "Distance1",
        "suppressed": True,
        "component": "",
        "configuration": "",
    }


def test_unsuppress_mate_success() -> None:
    mate = _FakeMate("Distance1", suppressed=True)
    adapter = _adapter_with(_MateModel(mates=[mate]))

    result = assembly_module._suppress_mate_impl(
        adapter, SuppressMateParameters(name="Distance1", suppress=False)
    )

    assert result.is_success
    assert mate.suppression_calls == [(1, 2)]
    assert result.data == {
        "name": "Distance1",
        "suppressed": False,
        "component": "",
        "configuration": "",
    }


def test_suppress_mate_scoped_to_configuration() -> None:
    """A configuration name routes to swSpecifyConfiguration and is verified
    against that configuration (already active here, so no switch needed)."""
    mate = _FakeMate("Distance1")
    model = _MateModel(mates=[mate])
    model.ConfigurationManager = SimpleNamespace(
        ActiveConfiguration=SimpleNamespace(Name="cone_disengaged")
    )
    model.ShowConfiguration2 = lambda name: True
    adapter = _adapter_with(model)

    result = assembly_module._suppress_mate_impl(
        adapter,
        SuppressMateParameters(
            name="Distance1", suppress=True, configuration="cone_disengaged"
        ),
    )

    assert result.is_success
    assert mate.suppression_calls == [(0, 3)]  # suppress, specify configuration
    assert result.data == {
        "name": "Distance1",
        "suppressed": True,
        "component": "",
        "configuration": "cone_disengaged",
    }


def test_suppress_mate_configuration_with_component_errors() -> None:
    result = assembly_module._suppress_mate_impl(
        _adapter_with(_MateModel(mates=[_FakeMate("Distance1")])),
        SuppressMateParameters(
            name="Distance1", configuration="rest", component="drive-train-1"
        ),
    )
    assert result.is_error
    assert "not supported together with component" in (result.error or "")


def test_suppress_mate_state_not_applied_errors() -> None:
    mate = _FakeMate("Distance1")
    mate.suppression_applies = False
    adapter = _adapter_with(_MateModel(mates=[mate]))

    result = assembly_module._suppress_mate_impl(
        adapter, SuppressMateParameters(name="Distance1", suppress=True)
    )
    assert result.is_error
    assert "did not become suppressed" in (result.error or "")


def test_suppress_mate_unknown_errors() -> None:
    adapter = _adapter_with(_MateModel())
    result = assembly_module._suppress_mate_impl(
        adapter, SuppressMateParameters(name="Ghost1")
    )
    assert result.is_error
    assert "Mate not found" in (result.error or "")


# ---------------------------------------------------------------------------
# Sub-scoped suppression + flexibility (PR-M4)
# ---------------------------------------------------------------------------


class _SubComponent:
    """A component whose GetModelDoc2 returns a (sub-assembly) model doc."""

    def __init__(self, name, sub_model) -> None:
        self.Name2 = name
        self._sub_model = sub_model

    def GetModelDoc2(self):  # noqa: N802
        return self._sub_model


def test_suppress_mate_in_subassembly_resolves_in_sub_doc() -> None:
    # The driver mate lives only in the sub's model doc, not the top level.
    driver = _FakeMate("Distance34", type_name="MateDistanceDim")
    sub_model = _MateModel(mates=[driver])
    top = _FakeAssemblyModel(
        components={"drive-train-1": _SubComponent("drive-train-1", sub_model)}
    )
    adapter = _adapter_with(top)

    result = assembly_module._suppress_mate_impl(
        adapter,
        SuppressMateParameters(
            name="Distance34", suppress=True, component="drive-train-1"
        ),
    )
    assert result.is_success
    assert driver.suppression_calls == [(0, 2)]  # suppressed in the sub doc
    assert result.data == {
        "name": "Distance34",
        "suppressed": True,
        "component": "drive-train-1",
        "configuration": "",
    }


def test_suppress_mate_in_subassembly_missing_component_errors() -> None:
    adapter = _adapter_with(_FakeAssemblyModel(components={}))
    result = assembly_module._suppress_mate_impl(
        adapter,
        SuppressMateParameters(name="Distance34", component="ghost-1"),
    )
    assert result.is_error
    assert "Component not found" in (result.error or "")


def test_suppress_mate_in_subassembly_mate_missing_errors() -> None:
    sub_model = _MateModel(mates=[])
    top = _FakeAssemblyModel(
        components={"drive-train-1": _SubComponent("drive-train-1", sub_model)}
    )
    adapter = _adapter_with(top)
    result = assembly_module._suppress_mate_impl(
        adapter,
        SuppressMateParameters(name="Distance34", component="drive-train-1"),
    )
    assert result.is_error
    assert "in 'drive-train-1'" in (result.error or "")


class _SolvingComponent(_FakeComponent):
    def __init__(self, name="drive-train-1", solving=0) -> None:
        super().__init__(name=name)
        self.Solving = solving


class _SolvingModel(_FakeAssemblyModel):
    """Assembly model whose CompConfigProperties5 flips the component's Solving."""

    def __init__(self, components=None, takes=True) -> None:
        super().__init__(components=components)
        self.takes = takes
        self.config_calls: list[tuple] = []

    def CompConfigProperties5(  # noqa: N802
        self, status, solving, named, suppression, config, preview, lightweight
    ):
        self.config_calls.append((status, solving))
        if self.takes:
            for comp in self._components.values():
                comp.Solving = solving
        return True


def test_set_component_solving_flexible_success() -> None:
    comp = _SolvingComponent(solving=0)
    model = _SolvingModel(components={"drive-train-1": comp})
    adapter = _adapter_with(model)

    result = assembly_module._set_component_solving_impl(
        adapter,
        assembly_module.SetComponentSolvingParameters(
            name="drive-train-1", solving="flexible"
        ),
    )
    assert result.is_success
    assert result.data == {"name": "drive-train-1", "solving": "flexible"}
    assert model.config_calls == [(2, 1)]  # fully resolved, flexible


def test_set_component_solving_unknown_mode_errors() -> None:
    model = _SolvingModel(components={"drive-train-1": _SolvingComponent()})
    adapter = _adapter_with(model)
    result = assembly_module._set_component_solving_impl(
        adapter,
        assembly_module.SetComponentSolvingParameters(
            name="drive-train-1", solving="squishy"
        ),
    )
    assert result.is_error
    assert "Unknown solving mode" in (result.error or "")


def test_set_component_solving_refusal_reports_readback() -> None:
    comp = _SolvingComponent(solving=0)
    model = _SolvingModel(components={"drive-train-1": comp}, takes=False)
    adapter = _adapter_with(model)
    result = assembly_module._set_component_solving_impl(
        adapter,
        assembly_module.SetComponentSolvingParameters(
            name="drive-train-1", solving="flexible"
        ),
    )
    assert result.is_error
    assert "did not take" in (result.error or "")
    assert "float it first" in (result.error or "")


class _RefConfigModel(_FakeAssemblyModel):
    """Assembly model whose CompConfigProperties5 sets a component's referenced
    child configuration (empty RefConfigName restores 'Default', mirroring SW)."""

    def __init__(self, components=None, takes=True) -> None:
        super().__init__(components=components)
        self.takes = takes
        self.config_calls: list[tuple] = []

    def CompConfigProperties5(  # noqa: N802
        self, suppression, solving, visibility, named, config, bom, envelope
    ):
        self.config_calls.append((suppression, solving, config))
        if self.takes:
            for comp in self._components.values():
                comp.ReferencedConfiguration = config or "Default"
        return True


def test_set_component_configuration_success() -> None:
    comp = _SolvingComponent(solving=1)  # flexible — must be preserved
    model = _RefConfigModel(components={"drive-train-1": comp})
    adapter = _adapter_with(model)

    result = assembly_module._set_component_configuration_impl(
        adapter,
        SetComponentConfigurationParameters(
            name="drive-train-1", configuration="cone_disengaged"
        ),
    )
    assert result.is_success
    assert result.data == {"name": "drive-train-1", "configuration": "cone_disengaged"}
    # Suppression stays fully-resolved (2) and the flexible solve mode (1) is
    # preserved while the referenced child config is set.
    assert model.config_calls == [(2, 1, "cone_disengaged")]
    assert model.rebuilds == 1  # EditRebuild3 required for the change to show


def test_set_component_configuration_empty_restores_default() -> None:
    comp = _SolvingComponent(solving=0)
    model = _RefConfigModel(components={"drive-train-1": comp})
    adapter = _adapter_with(model)

    result = assembly_module._set_component_configuration_impl(
        adapter,
        SetComponentConfigurationParameters(name="drive-train-1", configuration=""),
    )
    assert result.is_success
    assert result.data == {"name": "drive-train-1", "configuration": "Default"}
    assert model.config_calls == [(2, 0, "")]  # empty RefConfigName = default


def test_set_component_configuration_component_not_found_errors() -> None:
    model = _RefConfigModel(components={})
    adapter = _adapter_with(model)
    result = assembly_module._set_component_configuration_impl(
        adapter,
        SetComponentConfigurationParameters(
            name="missing-1", configuration="cone_disengaged"
        ),
    )
    assert result.is_error
    assert "Component not found" in (result.error or "")


def test_set_component_configuration_readback_mismatch_errors() -> None:
    comp = _SolvingComponent(solving=0)  # ReferencedConfiguration stays 'Default'
    model = _RefConfigModel(components={"drive-train-1": comp}, takes=False)
    adapter = _adapter_with(model)
    result = assembly_module._set_component_configuration_impl(
        adapter,
        SetComponentConfigurationParameters(
            name="drive-train-1", configuration="cone_disengaged"
        ),
    )
    assert result.is_error
    assert "did not take" in (result.error or "")


# ---------------------------------------------------------------------------
# Component cylindrical-face resolution (PR-M4 motor entity)
# ---------------------------------------------------------------------------


class _FakeSurface:
    def __init__(self, cyl) -> None:
        self._cyl = cyl  # None => not a cylinder

    def IsCylinder(self):  # noqa: N802
        return self._cyl is not None

    @property
    def CylinderParams(self):  # noqa: N802
        return self._cyl


class _FakeFace:
    def __init__(self, surface, area) -> None:
        self._surface = surface
        self._area = area
        self._next = None

    def GetSurface(self):  # noqa: N802
        return self._surface

    def GetArea(self):  # noqa: N802
        return self._area

    def GetNextFace(self):  # noqa: N802
        return self._next


class _FakeBody:
    def __init__(self, faces) -> None:
        self._faces = list(faces)
        for face, succ in zip(self._faces, self._faces[1:], strict=False):
            face._next = succ
        if self._faces:
            self._faces[-1]._next = None

    def GetFirstFace(self):  # noqa: N802
        return self._faces[0] if self._faces else None


class _FacePartComponent:
    def __init__(self, name, bodies) -> None:
        self.Name2 = name
        self._bodies = bodies
        self.corresponded: list[object] = []

    def GetModelDoc2(self):  # noqa: N802
        return SimpleNamespace(GetBodies2=lambda body_type, visible: self._bodies)

    def GetCorrespondingEntity(self, face):  # noqa: N802
        self.corresponded.append(face)
        return ("assembly-face", face)


def test_component_cylindrical_face_picks_largest_area() -> None:
    small = _FakeFace(_FakeSurface([0, 0, 0, 0, 1, 0, 0.0025]), area=1.0)
    big = _FakeFace(_FakeSurface([0, 0, 0, 0, 1, 0, 0.0047]), area=9.0)
    flat = _FakeFace(_FakeSurface(None), area=99.0)  # ignored (not a cylinder)
    comp = _FacePartComponent("drive-train-1/crankshaft-1", [_FakeBody([small, flat, big])])
    top = _FakeAssemblyModel(components={"drive-train-1/crankshaft-1": comp})
    adapter = _adapter_with(top)

    result = assembly_module._component_cylindrical_face(
        adapter, "drive-train-1/crankshaft-1"
    )
    assert result == ("assembly-face", big)
    assert comp.corresponded == [big]


def test_component_cylindrical_face_disambiguates_by_point() -> None:
    # Two equal-area cylinders on parallel axes; the point sits on the second.
    near_origin = _FakeFace(_FakeSurface([0, 0, 0, 0, 0, 1, 0.003]), area=5.0)
    offset = _FakeFace(_FakeSurface([0.1, 0, 0, 0, 0, 1, 0.003]), area=5.0)
    comp = _FacePartComponent("sub-1/shaft-1", [_FakeBody([near_origin, offset])])
    top = _FakeAssemblyModel(components={"sub-1/shaft-1": comp})
    adapter = _adapter_with(top)

    result = assembly_module._component_cylindrical_face(
        adapter, "sub-1/shaft-1", point=[100.0, 0.0, 0.0]
    )
    assert result == ("assembly-face", offset)


class _NestedModel(_FakeAssemblyModel):
    """Assembly whose GetComponentByName resolves only top-level instances.

    Nested 'sub-1/part-1' must come from the GetComponents(False) Name2 scan,
    mirroring the SolidWorks versions where GetComponentByName returns None for
    a nested path.
    """

    def __init__(self, top=None, nested=None) -> None:
        super().__init__(components=top or {})
        self._all = list((top or {}).values()) + list(nested or [])

    def GetComponents(self, top_only):  # noqa: N802
        return [] if top_only else self._all


def test_get_component_falls_back_to_name2_scan_for_nested() -> None:
    nested = _FakeComponent(name="drive-train-1/crankshaft-1")
    model = _NestedModel(top={"drive-train-1": _FakeComponent("drive-train-1")},
                         nested=[nested])
    adapter = _adapter_with(model)

    found = assembly_module._get_component(adapter, "drive-train-1/crankshaft-1")
    assert found is nested


def test_component_cylindrical_face_no_cylinder_returns_none() -> None:
    flat = _FakeFace(_FakeSurface(None), area=10.0)
    comp = _FacePartComponent("sub-1/block-1", [_FakeBody([flat])])
    top = _FakeAssemblyModel(components={"sub-1/block-1": comp})
    adapter = _adapter_with(top)
    assert (
        assembly_module._component_cylindrical_face(adapter, "sub-1/block-1") is None
    )


class _NamedFeatureComponent:
    """Component whose part doc resolves a named feature; GetCorresponding maps
    it into assembly context (the GetCorresponding sibling -- features, not
    just entities)."""

    def __init__(self, name, features) -> None:
        self.Name2 = name
        self._features = dict(features)
        self.corresponded: list[object] = []

    def GetModelDoc2(self):  # noqa: N802
        return SimpleNamespace(FeatureByName=lambda n: self._features.get(n))

    def GetCorresponding(self, feat):  # noqa: N802
        self.corresponded.append(feat)
        return ("assembly-feature", feat)


def test_component_named_feature_maps_via_getcorresponding() -> None:
    axis = SimpleNamespace(Name="Axis3")
    comp = _NamedFeatureComponent("drive-train-1/cylinder-gear-1", {"Axis3": axis})
    top = _FakeAssemblyModel(components={"drive-train-1/cylinder-gear-1": comp})
    adapter = _adapter_with(top)

    result = assembly_module._component_named_feature(
        adapter, "drive-train-1/cylinder-gear-1", "Axis3"
    )
    assert result == ("assembly-feature", axis)
    assert comp.corresponded == [axis]


def test_component_named_feature_missing_feature_returns_none() -> None:
    comp = _NamedFeatureComponent("sub-1/part-1", {"Axis1": object()})
    top = _FakeAssemblyModel(components={"sub-1/part-1": comp})
    adapter = _adapter_with(top)
    assert (
        assembly_module._component_named_feature(adapter, "sub-1/part-1", "Axis9")
        is None
    )


def test_select_mate_entity_component_name_selects_mapped_feature() -> None:
    selected = SimpleNamespace(Select2=lambda append, mark: True)
    comp = _NamedFeatureComponent("channel-1/connecting-rod-1", {"Axis1": object()})
    comp.GetCorresponding = lambda feat: selected  # type: ignore[method-assign]
    top = _FakeAssemblyModel(components={"channel-1/connecting-rod-1": comp})
    adapter = _adapter_with(top)
    ref = MateEntityRef(
        entity_type="AXIS", component="channel-1/connecting-rod-1", name="Axis1"
    )
    assert assembly_module._select_mate_entity(adapter, ref, mark=1) is True


# ---------------------------------------------------------------------------
# Mock adapter parity (Phase 7B)
# ---------------------------------------------------------------------------


async def _connected_mock() -> MockSolidWorksAdapter:
    adapter = MockSolidWorksAdapter(
        {"mock_connect_delay": 0, "mock_model_delay": 0, "mock_sketch_delay": 0}
    )
    await adapter.connect()
    await adapter.create_part()
    return adapter


async def _assembly_mock_with_component() -> tuple[MockSolidWorksAdapter, str]:
    adapter = MockSolidWorksAdapter(
        {"mock_connect_delay": 0, "mock_model_delay": 0, "mock_sketch_delay": 0}
    )
    await adapter.connect()
    await adapter.create_assembly()
    inserted = await adapter.insert_component(
        InsertComponentParameters(file_path="C:/parts/drive-train.sldasm")
    )
    return adapter, inserted.data["name"]


@pytest.mark.asyncio
async def test_mock_set_component_solving_float_then_flexible() -> None:
    adapter, name = await _assembly_mock_with_component()
    # A freshly inserted component is fixed; flexible is refused until floated.
    refused = await adapter.set_component_solving(
        SetComponentSolvingParameters(name=name, solving="flexible")
    )
    assert refused.is_error
    assert "float it first" in (refused.error or "")

    await adapter.float_component(ComponentRefParameters(name=name))
    flexed = await adapter.set_component_solving(
        SetComponentSolvingParameters(name=name, solving="flexible")
    )
    assert flexed.is_success
    assert flexed.data == {"name": name, "solving": "flexible"}


@pytest.mark.asyncio
async def test_mock_set_component_solving_unknown_mode_errors() -> None:
    adapter, name = await _assembly_mock_with_component()
    result = await adapter.set_component_solving(
        SetComponentSolvingParameters(name=name, solving="rigidish")
    )
    assert result.is_error
    assert "Unknown solving mode" in (result.error or "")


async def _assembly_mock_with_two_components() -> tuple[MockSolidWorksAdapter, list[str]]:
    adapter = MockSolidWorksAdapter(
        {"mock_connect_delay": 0, "mock_model_delay": 0, "mock_sketch_delay": 0}
    )
    await adapter.connect()
    await adapter.create_assembly()
    names = []
    for path in ("C:/parts/sprocket-t12.sldprt", "C:/parts/sprocket-t24.sldprt"):
        inserted = await adapter.insert_component(
            InsertComponentParameters(file_path=path)
        )
        names.append(inserted.data["name"])
    return adapter, names


@pytest.mark.asyncio
async def test_mock_insert_belt_chain_success() -> None:
    adapter, names = await _assembly_mock_with_two_components()
    result = await adapter.insert_belt_chain(
        BeltChainParameters(
            pulley_components=names,
            pulley_diameters=[24.0, 48.0],
            engage_belt=True,
        )
    )
    assert result.is_success
    assert result.data.type == "BeltChain"
    assert result.data.parameters["pulleys"] == 2
    assert result.data.parameters["engage_belt"] is True


@pytest.mark.asyncio
async def test_mock_insert_belt_chain_requires_two_pulleys() -> None:
    adapter, names = await _assembly_mock_with_two_components()
    result = await adapter.insert_belt_chain(
        BeltChainParameters(
            pulley_components=names[:1], pulley_diameters=[24.0]
        )
    )
    assert result.is_error
    assert "at least 2 pulley_components" in (result.error or "")


@pytest.mark.asyncio
async def test_mock_blank_sketch_records_and_requires_model() -> None:
    adapter = MockSolidWorksAdapter(
        {"mock_connect_delay": 0, "mock_model_delay": 0, "mock_sketch_delay": 0}
    )
    await adapter.connect()
    no_model = await adapter.blank_sketch("chain-path")
    assert no_model.is_error
    assert "No active model" in (no_model.error or "")

    await adapter.create_assembly()
    ok = await adapter.blank_sketch("chain-path")
    assert ok.is_success
    assert "chain-path" in adapter._blanked_sketches


@pytest.mark.asyncio
async def test_mock_insert_belt_chain_component_not_found() -> None:
    adapter, names = await _assembly_mock_with_two_components()
    result = await adapter.insert_belt_chain(
        BeltChainParameters(
            pulley_components=[names[0], "ghost-1"],
            pulley_diameters=[24.0, 48.0],
        )
    )
    assert result.is_error
    assert "Pulley component not found" in (result.error or "")


@pytest.mark.asyncio
async def test_mock_set_component_configuration_sets_and_restores() -> None:
    adapter, name = await _assembly_mock_with_component()
    set_result = await adapter.set_component_configuration(
        SetComponentConfigurationParameters(name=name, configuration="cone_disengaged")
    )
    assert set_result.is_success
    assert set_result.data == {"name": name, "configuration": "cone_disengaged"}

    restored = await adapter.set_component_configuration(
        SetComponentConfigurationParameters(name=name, configuration="")
    )
    assert restored.is_success
    assert restored.data == {"name": name, "configuration": "Default"}


@pytest.mark.asyncio
async def test_mock_set_component_configuration_not_found_errors() -> None:
    adapter, _ = await _assembly_mock_with_component()
    result = await adapter.set_component_configuration(
        SetComponentConfigurationParameters(name="ghost-1", configuration="x")
    )
    assert result.is_error
    assert "Component not found" in (result.error or "")


@pytest.mark.asyncio
async def test_mock_suppress_mate_in_subassembly_records_component() -> None:
    adapter, name = await _assembly_mock_with_component()
    result = await adapter.suppress_mate(
        SuppressMateParameters(name="Distance34", suppress=True, component=name)
    )
    assert result.is_success
    assert result.data == {
        "name": "Distance34",
        "suppressed": True,
        "component": name,
    }
    assert adapter._sub_suppressed_mates[(name, "Distance34")] is True


@pytest.mark.asyncio
async def test_mock_add_mate_names_by_type_and_lists() -> None:
    adapter = await _connected_mock()

    first = await adapter.add_mate(
        AddMateParameters(mate_type="coincident", entities=_two_entities())
    )
    second = await adapter.add_mate(
        AddMateParameters(mate_type="coincident", entities=_two_entities())
    )
    other = await adapter.add_mate(
        AddMateParameters(mate_type="distance", entities=_two_entities())
    )

    assert first.data["name"] == "Coincident1"
    assert second.data["name"] == "Coincident2"
    assert other.data["name"] == "Distance1"

    listed = await adapter.list_mates()
    assert [m["name"] for m in listed.data] == [
        "Coincident1",
        "Coincident2",
        "Distance1",
    ]
    assert all(m["suppressed"] is False for m in listed.data)


@pytest.mark.asyncio
async def test_mock_add_mate_mirrors_impl_validations() -> None:
    adapter = await _connected_mock()

    bad_type = await adapter.add_mate(
        AddMateParameters(mate_type="magnetic", entities=_two_entities())
    )
    assert bad_type.is_error
    assert "Unknown mate_type" in (bad_type.error or "")

    bad_alignment = await adapter.add_mate(
        AddMateParameters(
            mate_type="coincident", entities=_two_entities(), alignment="x"
        )
    )
    assert bad_alignment.is_error
    assert "Unknown alignment" in (bad_alignment.error or "")

    too_few = await adapter.add_mate(
        AddMateParameters(mate_type="width", entities=_two_entities())
    )
    assert too_few.is_error
    assert "at least 4 entities" in (too_few.error or "")

    bad_limits = await adapter.add_mate(
        AddMateParameters(
            mate_type="angle", entities=_two_entities(), angle_limits=[1.0]
        )
    )
    assert bad_limits.is_error
    assert "angle_limits must be [min, max]" in (bad_limits.error or "")


@pytest.mark.asyncio
async def test_mock_delete_and_suppress_mate_round_trip() -> None:
    adapter = await _connected_mock()
    await adapter.add_mate(
        AddMateParameters(mate_type="tangent", entities=_two_entities())
    )

    suppressed = await adapter.suppress_mate(
        SuppressMateParameters(name="Tangent1", suppress=True)
    )
    assert suppressed.data == {
        "name": "Tangent1",
        "suppressed": True,
        "component": "",
    }
    listed = await adapter.list_mates()
    assert listed.data[0]["suppressed"] is True

    deleted = await adapter.delete_mate(MateRefParameters(name="Tangent1"))
    assert deleted.data == {"name": "Tangent1", "removed": True}
    assert (await adapter.list_mates()).data == []

    missing = await adapter.delete_mate(MateRefParameters(name="Tangent1"))
    assert missing.is_error
    assert "Mate not found" in (missing.error or "")


# ---------------------------------------------------------------------------
# Mechanical mates (Phase 7C)
# ---------------------------------------------------------------------------


def test_add_mate_gear_sets_ratio_on_mate_data() -> None:
    model = _MateModel()
    model.add_mate_name = "GearMate1"
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="gear", entities=_two_entities(), gear_ratio=[24, 12]
        ),
    )

    assert result.is_success
    assert model.create_mate_data_calls == [10]  # CreateMateData(swMateGEAR)
    data = model.created_mate_data[0]
    assert data.GearRatioNumerator == 24.0
    assert data.GearRatioDenominator == 12.0
    assert result.data["gear_ratio"] == [24.0, 12.0]
    # Gear entities use the standard mark 1
    assert all(mark == 1 for (_, _, mark) in model.selections)


def test_add_mate_gear_ratio_validations() -> None:
    adapter = _adapter_with(_MateModel())

    wrong_length = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="gear", entities=_two_entities(), gear_ratio=[24.0]
        ),
    )
    assert wrong_length.is_error
    assert "gear_ratio must be [numerator, denominator]" in (wrong_length.error or "")

    wrong_type = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="coincident", entities=_two_entities(), gear_ratio=[24, 12]
        ),
    )
    assert wrong_type.is_error
    assert "only valid for gear mates" in (wrong_type.error or "")

    non_positive = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="gear", entities=_two_entities(), gear_ratio=[24, 0]
        ),
    )
    assert non_positive.is_error
    assert "must be positive" in (non_positive.error or "")


def test_add_mate_cam_follower_uses_mark_8() -> None:
    model = _MateModel()
    model.add_mate_name = "CamMate1"
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter, AddMateParameters(mate_type="cam_follower", entities=_two_entities())
    )

    assert result.is_success
    assert model.create_mate_data_calls == [9]  # CreateMateData(swMateCAMFOLLOWER)
    assert all(mark == 8 for (_, _, mark) in model.selections)


def test_add_mate_rack_pinion_sets_pitch_diameter() -> None:
    model = _MateModel()
    model.add_mate_name = "RackPinionMate1"
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="rack_pinion",
            entities=_two_entities(),
            pinion_pitch_diameter=30.0,
        ),
    )

    # Rack-pinion mates carrying a value take the dedicated mechanical builder:
    # CreateMateData -> set the diameter members up front -> CreateMate.
    assert result.is_success
    assert model.create_mate_data_calls == [13]  # CreateMateData(swMateRACKPINION)
    data = model.created_mate_data[-1]
    assert data.DiameterType == 0  # swPinionPitchDiameter
    assert abs(data.DiameterVal - 0.030) < 1e-12  # metres
    assert data.Reverse is False
    assert result.data["name"] == "RackPinionMate1"
    assert result.data["pinion_pitch_diameter"] == 30.0


def test_add_mate_rack_pinion_travel_per_revolution() -> None:
    model = _MateModel()
    model.add_mate_name = "RackPinionMate1"
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="rack_pinion",
            entities=_two_entities(),
            rack_travel_per_revolution=25.4,
        ),
    )

    assert result.is_success
    assert model.create_mate_data_calls == [13]
    data = model.created_mate_data[-1]
    assert data.DiameterType == 1  # swRackTravelPerRevolution
    assert abs(data.DiameterVal - 0.0254) < 1e-12
    assert result.data["rack_travel_per_revolution"] == 25.4


def test_add_mate_rack_pinion_both_values_errors() -> None:
    adapter = _adapter_with(_MateModel())
    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="rack_pinion",
            entities=_two_entities(),
            pinion_pitch_diameter=30.0,
            rack_travel_per_revolution=25.4,
        ),
    )
    assert result.is_error
    assert "not both" in (result.error or "")


def test_add_mate_rack_pinion_requires_a_value() -> None:
    # A value-less rack_pinion mate cannot be derived by CreateMate (unlike the
    # old AddMate5 path), so it is rejected up front rather than silently falling
    # through to a standard mate that omits DiameterType/DiameterVal.
    adapter = _adapter_with(_MateModel())
    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="rack_pinion",
            entities=_two_entities(),
        ),
    )
    assert result.is_error
    assert "require" in (result.error or "")
    assert "pinion_pitch_diameter" in (result.error or "")


def test_add_mate_screw_sets_distance_per_revolution() -> None:
    model = _MateModel()
    model.add_mate_name = "ScrewMate1"
    adapter = _adapter_with(model)

    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="screw",
            entities=_two_entities(),
            distance_per_revolution=2.0,
        ),
    )

    assert result.is_success
    assert model.create_mate_data_calls == [17]  # CreateMateData(swMateSCREW)
    data = model.created_mate_data[0]
    assert data.RevolutionType == 1  # swDistancePerRevolution
    assert abs(data.RevolutionVal - 0.002) < 1e-12
    assert result.data["distance_per_revolution"] == 2.0


def test_add_mate_mechanical_value_on_wrong_type_errors() -> None:
    adapter = _adapter_with(_MateModel())
    result = assembly_module._add_mate_impl(
        adapter,
        AddMateParameters(
            mate_type="coincident",
            entities=_two_entities(),
            distance_per_revolution=2.0,
        ),
    )
    assert result.is_error
    assert "only valid for screw mates" in (result.error or "")




@pytest.mark.asyncio
async def test_mock_mechanical_mates_parity() -> None:
    adapter = await _connected_mock()

    gear = await adapter.add_mate(
        AddMateParameters(
            mate_type="gear", entities=_two_entities(), gear_ratio=[24, 12]
        )
    )
    assert gear.data["name"] == "Gear1"
    assert gear.data["gear_ratio"] == [24.0, 12.0]

    rack = await adapter.add_mate(
        AddMateParameters(
            mate_type="rack_pinion",
            entities=_two_entities(),
            pinion_pitch_diameter=30.0,
        )
    )
    assert rack.data["name"] == "RackPinion1"
    assert rack.data["pinion_pitch_diameter"] == 30.0

    cam = await adapter.add_mate(
        AddMateParameters(mate_type="cam_follower", entities=_two_entities())
    )
    assert cam.data["name"] == "CamFollower1"

    screw = await adapter.add_mate(
        AddMateParameters(
            mate_type="screw", entities=_two_entities(), distance_per_revolution=2.0
        )
    )
    assert screw.data["name"] == "Screw1"
    assert screw.data["distance_per_revolution"] == 2.0


@pytest.mark.asyncio
async def test_mock_mechanical_mates_validations() -> None:
    adapter = await _connected_mock()

    wrong_type = await adapter.add_mate(
        AddMateParameters(
            mate_type="coincident", entities=_two_entities(), gear_ratio=[2, 1]
        )
    )
    assert wrong_type.is_error
    assert "only valid for gear mates" in (wrong_type.error or "")

    both = await adapter.add_mate(
        AddMateParameters(
            mate_type="rack_pinion",
            entities=_two_entities(),
            pinion_pitch_diameter=30.0,
            rack_travel_per_revolution=25.4,
        )
    )
    assert both.is_error
    assert "not both" in (both.error or "")


# ---------------------------------------------------------------------------
# rotate_component mode="kinematic" — gear-mate propagation (Phase 7C)
# ---------------------------------------------------------------------------


def _gear_axis(point_m, vector) -> list[float]:
    """EntityParams layout: point, direction, radius1, radius2 (metres)."""
    return list(point_m) + list(vector) + [0.0, 0.0]


class _FakeGearMateFeature(_FakeMate):
    """A mate-group subfeature carrying a gear mate (swMateGEAR = 10)."""

    def __init__(
        self, name, sides, numerator, denominator, reverse=False, suppressed=False
    ) -> None:
        super().__init__(name, type_name="MateGear", suppressed=suppressed)
        self.definition = SimpleNamespace(
            GearRatioNumerator=numerator,
            GearRatioDenominator=denominator,
            Reverse=reverse,
        )
        entities = [
            SimpleNamespace(
                ReferenceComponent=SimpleNamespace(Name2=component),
                EntityParams=list(params),
            )
            for component, params in sides
        ]
        self._mate = SimpleNamespace(Type=10, MateEntity=lambda i: entities[i])

    def GetSpecificFeature2(self):  # noqa: N802
        return self._mate


def _kinematic_fixture(mates, components) -> _FakeAdapter:
    model = _MateModel(mates=mates)
    model._components.update(components)
    return _adapter_with(model)


def test_rotate_component_kinematic_rotates_partner_by_inverse_ratio() -> None:
    """gear_ratio [30, 15] stores num=15/den=30 (live-verified swap); the
    side-1 partner must counter-rotate by -den/num = -2x about its own axis."""
    big = _FakeComponent(name="big-1")
    small = _FakeComponent(
        name="small-1",
        array16=[1, 0, 0, 0, 1, 0, 0, 0, 1, 0.045, 0.0, 0.0, 1, 0, 0, 0],
    )
    mate = _FakeGearMateFeature(
        "GearMate1",
        sides=[
            ("big-1", _gear_axis([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])),
            ("small-1", _gear_axis([0.045, 0.0, 0.0], [0.0, 0.0, 1.0])),
        ],
        numerator=15.0,
        denominator=30.0,
    )
    adapter = _kinematic_fixture([mate], {"big-1": big, "small-1": small})

    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(name="big-1", angle=45, mode="kinematic"),
    )

    assert result.is_success
    assert result.data["propagated"] == [
        {"component": "small-1", "angle": -90.0, "mate": "GearMate1"}
    ]
    applied = small.applied_arrays[0]
    # -90 deg about z: the component x-axis lands on -Y.
    _assert_close(applied[0:3], [0, -1, 0])
    # Rotation about the small gear's own axis keeps it in place.
    _assert_close(applied[9:12], [0.045, 0.0, 0.0])


def test_rotate_component_kinematic_chains_and_respects_side_order() -> None:
    """BFS reaches a second mate where the carrier sits on side 1, so the
    factor flips to -num/den; the input never re-rotates."""
    a = _FakeComponent(name="a-1")
    b = _FakeComponent(name="b-1")
    c = _FakeComponent(name="c-1")
    mate_ab = _FakeGearMateFeature(
        "GearMate1",
        sides=[
            ("a-1", _gear_axis([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])),
            ("b-1", _gear_axis([0.045, 0.0, 0.0], [0.0, 0.0, 1.0])),
        ],
        numerator=15.0,
        denominator=30.0,
    )
    mate_cb = _FakeGearMateFeature(
        "GearMate2",
        sides=[
            ("c-1", _gear_axis([0.09, 0.0, 0.0], [0.0, 0.0, 1.0])),
            ("b-1", _gear_axis([0.045, 0.0, 0.0], [0.0, 0.0, 1.0])),
        ],
        numerator=10.0,
        denominator=20.0,
    )
    adapter = _kinematic_fixture([mate_ab, mate_cb], {"a-1": a, "b-1": b, "c-1": c})

    result = assembly_module._rotate_component_impl(
        adapter, RotateComponentParameters(name="a-1", angle=45, mode="kinematic")
    )

    assert result.is_success
    # a +45 -> b = 45 * (-30/15) = -90 -> c = -90 * (-10/20) = +45.
    assert result.data["propagated"] == [
        {"component": "b-1", "angle": -90.0, "mate": "GearMate1"},
        {"component": "c-1", "angle": 45.0, "mate": "GearMate2"},
    ]
    assert len(a.applied_arrays) == 1  # the input is rotated exactly once


def test_rotate_component_kinematic_reverse_flag_flips_sign() -> None:
    big = _FakeComponent(name="big-1")
    small = _FakeComponent(name="small-1")
    mate = _FakeGearMateFeature(
        "GearMate1",
        sides=[
            ("big-1", _gear_axis([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])),
            ("small-1", _gear_axis([0.045, 0.0, 0.0], [0.0, 0.0, 1.0])),
        ],
        numerator=15.0,
        denominator=30.0,
        reverse=True,
    )
    adapter = _kinematic_fixture([mate], {"big-1": big, "small-1": small})

    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(name="big-1", angle=45, mode="kinematic"),
    )

    assert result.is_success
    assert result.data["propagated"][0]["angle"] == 90.0


def test_rotate_component_kinematic_skips_suppressed_gear_mate() -> None:
    big = _FakeComponent(name="big-1")
    small = _FakeComponent(name="small-1")
    mate = _FakeGearMateFeature(
        "GearMate1",
        sides=[
            ("big-1", _gear_axis([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])),
            ("small-1", _gear_axis([0.045, 0.0, 0.0], [0.0, 0.0, 1.0])),
        ],
        numerator=15.0,
        denominator=30.0,
        suppressed=True,
    )
    adapter = _kinematic_fixture([mate], {"big-1": big, "small-1": small})

    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(name="big-1", angle=45, mode="kinematic"),
    )

    assert result.is_success
    assert result.data["propagated"] == []
    assert small.applied_arrays == []


def test_rotate_component_kinematic_without_gear_mates_matches_exact() -> None:
    component = _FakeComponent()
    model = _FakeAssemblyModel(components={"shaft-1": component})
    adapter = _adapter_with(model)

    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(
            name="shaft-1",
            angle=90,
            axis_vector=[0, 0, 1],
            axis_point=[100, 0, 0],
            mode="kinematic",
        ),
    )

    assert result.is_success
    assert result.data["propagated"] == []
    _assert_close(result.data["position"], [100, -100, 0])


def test_rotate_component_kinematic_antiparallel_axes_counter_rotate() -> None:
    """Entity axis directions are modelling artefacts: when the partner's
    recorded axis points the other way, the propagated angle flips so the
    world-frame motion stays counter-rotating (+45 in -> -90 world out)."""
    big = _FakeComponent(name="big-1")
    small = _FakeComponent(name="small-1")
    mate = _FakeGearMateFeature(
        "GearMate1",
        sides=[
            ("big-1", _gear_axis([0.0, 0.0, 0.0], [0.0, 0.0, 1.0])),
            ("small-1", _gear_axis([0.045, 0.0, 0.0], [0.0, 0.0, -1.0])),
        ],
        numerator=15.0,
        denominator=30.0,
    )
    adapter = _kinematic_fixture([mate], {"big-1": big, "small-1": small})

    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(name="big-1", angle=45, mode="kinematic"),
    )

    assert result.is_success
    # +90 about the small gear's own -z axis == -90 in world space.
    assert result.data["propagated"][0]["angle"] == 90.0
    applied = small.applied_arrays[0]
    _assert_close(applied[0:3], [0, -1, 0])


def test_rotate_component_kinematic_input_axis_opposite_entity_axis() -> None:
    """The user's input axis may oppose the input's own mate-entity axis;
    the world-frame coupling must still counter-rotate."""
    big = _FakeComponent(name="big-1")
    small = _FakeComponent(name="small-1")
    mate = _FakeGearMateFeature(
        "GearMate1",
        sides=[
            ("big-1", _gear_axis([0.0, 0.0, 0.0], [0.0, 0.0, -1.0])),
            ("small-1", _gear_axis([0.045, 0.0, 0.0], [0.0, 0.0, -1.0])),
        ],
        numerator=15.0,
        denominator=30.0,
    )
    adapter = _kinematic_fixture([mate], {"big-1": big, "small-1": small})

    result = assembly_module._rotate_component_impl(
        adapter,
        RotateComponentParameters(name="big-1", angle=45, mode="kinematic"),
    )

    assert result.is_success
    # own swing = -45 about -z; coupled swing = +90 about -z = world -90.
    assert result.data["propagated"][0]["angle"] == 90.0
    applied = small.applied_arrays[0]
    _assert_close(applied[0:3], [0, -1, 0])
