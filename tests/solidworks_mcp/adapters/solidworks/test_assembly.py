"""Direct branch coverage tests for adapters.solidworks.assembly."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    ComponentCircularPatternParameters,
    ComponentLinearPatternParameters,
    ComponentRefParameters,
    InsertComponentParameters,
    MoveComponentParameters,
    ReplaceComponentParameters,
    RotateComponentParameters,
)
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
    def CreateTransform(self, array16):  # noqa: N802
        return SimpleNamespace(array16=list(array16))


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
