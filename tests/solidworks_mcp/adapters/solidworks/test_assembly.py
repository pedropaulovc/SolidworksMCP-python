"""Direct branch coverage tests for adapters.solidworks.assembly."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    AddMateParameters,
    ComponentCircularPatternParameters,
    ComponentLinearPatternParameters,
    ComponentRefParameters,
    InsertComponentParameters,
    MateEntityRef,
    MateRefParameters,
    MoveComponentParameters,
    ReplaceComponentParameters,
    RotateComponentParameters,
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
        self.mate_calls: list[tuple] = []
        self.point_selections: list[tuple] = []
        self.add_mate_name = "Coincident1"
        self.add_mate_status = 1
        self._last_feature = None

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

    def AddMate5(  # noqa: N802
        self,
        mate_type,
        alignment,
        flip,
        distance,
        distance_upper,
        distance_lower,
        gear_numerator,
        gear_denominator,
        angle,
        angle_upper,
        angle_lower,
        for_positioning,
        lock_rotation,
        width_option,
        error_status,
    ):
        self.mate_calls.append(
            (
                mate_type,
                alignment,
                flip,
                distance,
                distance_upper,
                distance_lower,
                gear_numerator,
                gear_denominator,
                angle,
                angle_upper,
                angle_lower,
                for_positioning,
                lock_rotation,
                width_option,
            )
        )
        try:
            error_status.value = self.add_mate_status
        except AttributeError:
            pass
        if self.add_mate_status != 1:
            return None
        mate = _FakeMate(self.add_mate_name)
        self.mate_group.mates.append(mate)
        return mate


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
        adapter, AddMateParameters(mate_type="gear", entities=_two_entities())
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
    call = model.mate_calls[0]
    assert call[0] == 1  # swMateCONCENTRIC
    assert call[1] == 1  # anti_aligned
    assert call[12] is True  # lock_rotation
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
    assert model.mate_calls[0][0] == 11  # swMateWIDTH


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
    call = model.mate_calls[0]
    assert abs(call[3] - 0.0254) < 1e-12  # distance in metres
    assert abs(call[4] - 0.050) < 1e-12  # upper limit
    assert abs(call[5] - 0.010) < 1e-12  # lower limit
    assert abs(call[8] - math.radians(90.0)) < 1e-12  # angle in radians
    assert abs(call[9] - math.radians(90.0)) < 1e-12  # no limits: upper = value


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
    assert result.data == {"name": "Distance1", "suppressed": True}


def test_unsuppress_mate_success() -> None:
    mate = _FakeMate("Distance1", suppressed=True)
    adapter = _adapter_with(_MateModel(mates=[mate]))

    result = assembly_module._suppress_mate_impl(
        adapter, SuppressMateParameters(name="Distance1", suppress=False)
    )

    assert result.is_success
    assert mate.suppression_calls == [(1, 2)]
    assert result.data == {"name": "Distance1", "suppressed": False}


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
# Mock adapter parity (Phase 7B)
# ---------------------------------------------------------------------------


async def _connected_mock() -> MockSolidWorksAdapter:
    adapter = MockSolidWorksAdapter(
        {"mock_connect_delay": 0, "mock_model_delay": 0, "mock_sketch_delay": 0}
    )
    await adapter.connect()
    await adapter.create_part()
    return adapter


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
        AddMateParameters(mate_type="gear", entities=_two_entities())
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
    assert suppressed.data == {"name": "Tangent1", "suppressed": True}
    listed = await adapter.list_mates()
    assert listed.data[0]["suppressed"] is True

    deleted = await adapter.delete_mate(MateRefParameters(name="Tangent1"))
    assert deleted.data == {"name": "Tangent1", "removed": True}
    assert (await adapter.list_mates()).data == []

    missing = await adapter.delete_mate(MateRefParameters(name="Tangent1"))
    assert missing.is_error
    assert "Mate not found" in (missing.error or "")
