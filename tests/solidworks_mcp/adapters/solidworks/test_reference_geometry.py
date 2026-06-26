"""Direct branch coverage tests for adapters.solidworks.reference_geometry."""

from __future__ import annotations

import math
from types import SimpleNamespace

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    CreateAxisParameters,
    CreateCoordinateSystemParameters,
    CreatePlaneParameters,
    CreateReferencePointParameters,
    RenameFeatureParameters,
)
from solidworks_mcp.adapters.solidworks import reference_geometry


class _FakeAdapter:
    def __init__(self) -> None:
        self.currentModel = None

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

    def _get_feature_id(self, feature):
        return getattr(feature, "Name", "feature-id")


def _model(**extra):
    """Fake currentModel: named features and point selections always succeed."""
    base = {
        "ClearSelection2": lambda *_a: True,
        "FeatureByName": lambda name: SimpleNamespace(
            Select2=lambda append, mark: True
        ),
        "Extension": SimpleNamespace(SelectByID2=lambda *a, **k: True),
        "FirstFeature": None,
    }
    base.update(extra)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# create_plane
# ---------------------------------------------------------------------------


def test_create_plane_offset_success_converts_units() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []

    def insert_ref_plane(*args):
        calls.append(args)
        return SimpleNamespace(Name="Plane1")

    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(InsertRefPlane=insert_ref_plane),
    )
    result = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(mode="offset", base_plane="Front Plane", offset=16.0),
    )
    assert result.is_success
    assert result.data.type == "RefPlane"
    assert result.data.name == "Plane1"
    # Distance constraint (8), 16 mm -> 0.016 m, no other constraints.
    assert calls == [(8, 0.016, 0, 0.0, 0, 0.0)]


def test_create_plane_offset_flip_sets_option_bit() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertRefPlane=lambda *a: calls.append(a) or SimpleNamespace(Name="Plane2")
        ),
    )
    result = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(
            mode="offset", base_plane="Front Plane", offset=7.5, flip=True
        ),
    )
    assert result.is_success
    assert calls[0][0] == 8 | 256  # Distance | OptionFlip


def test_create_plane_negative_offset_uses_abs_and_flip() -> None:
    """A negative offset must become a positive distance with OptionFlip set.

    InsertRefPlane clamps a negative Distance to 0 (collapsing the plane onto
    the base), so the sign is encoded by flipping the side instead.
    """
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertRefPlane=lambda *a: calls.append(a) or SimpleNamespace(Name="Plane2")
        ),
    )
    result = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(mode="offset", base_plane="Top Plane", offset=-5.08),
    )
    assert result.is_success
    constraint, distance, *_rest = calls[0]
    assert constraint == 8 | 256  # Distance | OptionFlip
    assert math.isclose(distance, 0.00508)  # magnitude, not -0.00508


def test_create_plane_negative_offset_with_flip_cancels_flip() -> None:
    """flip=True and a negative offset cancel: positive distance, no flip bit."""
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertRefPlane=lambda *a: calls.append(a) or SimpleNamespace(Name="Plane2")
        ),
    )
    result = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(
            mode="offset", base_plane="Top Plane", offset=-5.0, flip=True
        ),
    )
    assert result.is_success
    constraint, distance, *_rest = calls[0]
    assert constraint == 8  # Distance only (flip toggled back off)
    assert math.isclose(distance, 0.005)


def test_offset_plane_distance_helper() -> None:
    flip = reference_geometry._PLANE_OPTION_FLIP
    assert reference_geometry._offset_plane_distance(16.0, 0) == (0.016, 0)
    assert reference_geometry._offset_plane_distance(-16.0, 0) == (0.016, flip)
    assert reference_geometry._offset_plane_distance(16.0, flip) == (0.016, flip)
    assert reference_geometry._offset_plane_distance(-16.0, flip) == (0.016, 0)
    assert reference_geometry._offset_plane_distance(0.0, 0) == (0.0, 0)


def test_create_plane_angle_success() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertRefPlane=lambda *a: calls.append(a) or SimpleNamespace(Name="Plane3")
        ),
    )
    result = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(
            mode="angle",
            base_plane="Top Plane",
            angle=45.0,
            edge_point=[1.0, 2.0, 3.0],
        ),
    )
    assert result.is_success
    constraint, angle_rad, second, *_rest = calls[0]
    assert constraint == 16  # Angle
    assert math.isclose(angle_rad, math.radians(45.0))
    assert second == 4  # Coincident (the pivot edge)


def test_create_plane_three_point_success() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertRefPlane=lambda *a: calls.append(a) or SimpleNamespace(Name="Plane4")
        ),
    )
    result = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(
            mode="three_point",
            points=[[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [0.0, 10.0, 0.0]],
        ),
    )
    assert result.is_success
    assert calls == [(4, 0.0, 4, 0.0, 4, 0.0)]  # Coincident x3


def test_create_plane_parallel_point_success() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertRefPlane=lambda *a: calls.append(a) or SimpleNamespace(Name="Plane5")
        ),
    )
    result = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(
            mode="parallel_point",
            base_plane="Right Plane",
            points=[[5.0, 5.0, 5.0]],
        ),
    )
    assert result.is_success
    assert calls == [(1, 0.0, 4, 0.0, 0, 0.0)]  # Parallel + Coincident


def test_create_plane_guards() -> None:
    adapter = _FakeAdapter()
    no_model = reference_geometry._create_plane_impl(
        adapter, CreatePlaneParameters(mode="offset", base_plane="Front Plane")
    )
    assert no_model.error == "No active model"

    adapter.currentModel = SimpleNamespace()
    bad_mode = reference_geometry._create_plane_impl(
        adapter, CreatePlaneParameters(mode="bogus")
    )
    assert "mode must be one of" in (bad_mode.error or "")

    no_base = reference_geometry._create_plane_impl(
        adapter, CreatePlaneParameters(mode="offset")
    )
    assert "requires 'base_plane'" in (no_base.error or "")

    no_edge = reference_geometry._create_plane_impl(
        adapter, CreatePlaneParameters(mode="angle", base_plane="Top Plane")
    )
    assert "requires 'edge_point'" in (no_edge.error or "")

    two_points = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(mode="three_point", points=[[0, 0, 0], [1, 0, 0]]),
    )
    assert "exactly 3 points" in (two_points.error or "")

    no_point = reference_geometry._create_plane_impl(
        adapter, CreatePlaneParameters(mode="parallel_point", base_plane="Top Plane")
    )
    assert "exactly 1 point" in (no_point.error or "")


def test_create_plane_selection_failure() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = _model(
        FeatureByName=lambda name: None,
        FeatureManager=SimpleNamespace(
            InsertRefPlane=lambda *a: SimpleNamespace(Name="Plane1")
        ),
    )
    result = reference_geometry._create_plane_impl(
        adapter,
        CreatePlaneParameters(mode="offset", base_plane="Missing Plane", offset=1.0),
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "Failed to select base plane" in (result.error or "")


# ---------------------------------------------------------------------------
# create_axis
# ---------------------------------------------------------------------------


def test_create_axis_two_planes_success_resolves_by_tree_diff() -> None:
    adapter = _FakeAdapter()
    axis_node = SimpleNamespace(Name="Axis1", GetNextFeature=None)
    model = _model(InsertAxis2=None)  # placeholder, replaced below

    def insert_axis2(autosize):
        assert autosize is True
        model.FirstFeature = axis_node  # the new axis appears in the tree
        return True

    model.InsertAxis2 = insert_axis2
    adapter.currentModel = model
    result = reference_geometry._create_axis_impl(
        adapter,
        CreateAxisParameters(mode="two_planes", planes=["Front Plane", "Top Plane"]),
    )
    assert result.is_success
    assert result.data.type == "RefAxis"
    assert result.data.name == "Axis1"


def test_create_axis_cylindrical_face_success() -> None:
    adapter = _FakeAdapter()
    axis_node = SimpleNamespace(Name="Axis2", GetNextFeature=None)
    model = _model()

    def insert_axis2(_autosize):
        model.FirstFeature = axis_node
        return True

    model.InsertAxis2 = insert_axis2
    adapter.currentModel = model
    result = reference_geometry._create_axis_impl(
        adapter,
        CreateAxisParameters(mode="cylindrical_face", face_point=[4.76, 50.0, 0.0]),
    )
    assert result.is_success
    assert result.data.name == "Axis2"


def test_create_axis_failure_when_insert_returns_false() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = _model(InsertAxis2=lambda _autosize: False)
    result = reference_geometry._create_axis_impl(
        adapter,
        CreateAxisParameters(mode="two_planes", planes=["Front Plane", "Top Plane"]),
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "Failed to create reference axis" in (result.error or "")


def test_create_axis_guards() -> None:
    adapter = _FakeAdapter()
    no_model = reference_geometry._create_axis_impl(
        adapter, CreateAxisParameters(mode="edge", edge_point=[0, 0, 0])
    )
    assert no_model.error == "No active model"

    adapter.currentModel = SimpleNamespace()
    bad_mode = reference_geometry._create_axis_impl(
        adapter, CreateAxisParameters(mode="bogus")
    )
    assert "mode must be one of" in (bad_mode.error or "")

    one_plane = reference_geometry._create_axis_impl(
        adapter, CreateAxisParameters(mode="two_planes", planes=["Front Plane"])
    )
    assert "exactly 2 plane names" in (one_plane.error or "")

    no_face = reference_geometry._create_axis_impl(
        adapter, CreateAxisParameters(mode="cylindrical_face")
    )
    assert "requires 'face_point'" in (no_face.error or "")

    one_point = reference_geometry._create_axis_impl(
        adapter, CreateAxisParameters(mode="two_points", points=[[0, 0, 0]])
    )
    assert "exactly 2 points" in (one_point.error or "")

    no_edge = reference_geometry._create_axis_impl(
        adapter, CreateAxisParameters(mode="edge")
    )
    assert "requires 'edge_point'" in (no_edge.error or "")


# ---------------------------------------------------------------------------
# create_reference_point
# ---------------------------------------------------------------------------


def test_create_reference_point_face_center_success() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertReferencePoint=lambda *a: calls.append(a)
            or SimpleNamespace(Name="Point1")
        ),
    )
    result = reference_geometry._create_reference_point_impl(
        adapter,
        CreateReferencePointParameters(mode="face_center", face_point=[1.0, 2.0, 3.0]),
    )
    assert result.is_success
    assert result.data.type == "RefPoint"
    assert calls == [(4, 0, 0.0, 1)]  # swRefPointFaceCenter


def test_create_reference_point_arc_center_success() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertReferencePoint=lambda *a: calls.append(a)
            or SimpleNamespace(Name="Point2")
        ),
    )
    result = reference_geometry._create_reference_point_impl(
        adapter,
        CreateReferencePointParameters(mode="arc_center", edge_point=[25.5, 0.0, 1.5]),
    )
    assert result.is_success
    assert calls == [(3, 0, 0.0, 1)]  # swRefPointCenterEdge


def test_create_reference_point_along_curve_variants() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            InsertReferencePoint=lambda *a: calls.append(a)
            or SimpleNamespace(Name="Point3")
        ),
    )
    distance = reference_geometry._create_reference_point_impl(
        adapter,
        CreateReferencePointParameters(
            mode="along_curve", edge_point=[0, 0, 0], along="distance", distance=25.0
        ),
    )
    assert distance.is_success
    assert calls[-1] == (2, 0, 0.025, 1)  # 25 mm -> 0.025 m

    evenly = reference_geometry._create_reference_point_impl(
        adapter,
        CreateReferencePointParameters(
            mode="along_curve", edge_point=[0, 0, 0], along="evenly", count=5
        ),
    )
    assert evenly.is_success
    assert calls[-1] == (2, 2, 0.0, 5)

    percentage = reference_geometry._create_reference_point_impl(
        adapter,
        CreateReferencePointParameters(
            mode="along_curve",
            edge_point=[0, 0, 0],
            along="percentage",
            percentage=40.0,
        ),
    )
    assert percentage.is_success
    assert calls[-1] == (2, 1, 40.0, 1)  # percentage passes through


def test_create_reference_point_guards() -> None:
    adapter = _FakeAdapter()
    no_model = reference_geometry._create_reference_point_impl(
        adapter,
        CreateReferencePointParameters(mode="face_center", face_point=[0, 0, 0]),
    )
    assert no_model.error == "No active model"

    adapter.currentModel = SimpleNamespace()
    bad_mode = reference_geometry._create_reference_point_impl(
        adapter, CreateReferencePointParameters(mode="bogus")
    )
    assert "mode must be one of" in (bad_mode.error or "")

    no_face = reference_geometry._create_reference_point_impl(
        adapter, CreateReferencePointParameters(mode="face_center")
    )
    assert "requires 'face_point'" in (no_face.error or "")

    no_edge = reference_geometry._create_reference_point_impl(
        adapter, CreateReferencePointParameters(mode="arc_center")
    )
    assert "requires 'edge_point'" in (no_edge.error or "")

    bad_along = reference_geometry._create_reference_point_impl(
        adapter,
        CreateReferencePointParameters(
            mode="along_curve", edge_point=[0, 0, 0], along="bogus"
        ),
    )
    assert "'along' must be one of" in (bad_along.error or "")


# ---------------------------------------------------------------------------
# create_coordinate_system
# ---------------------------------------------------------------------------


def test_create_coordinate_system_success_converts_units() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            CreateCoordinateSystemUsingNumericalValues=lambda *a: calls.append(a)
            or SimpleNamespace(Name="Coordinate System1")
        ),
    )
    result = reference_geometry._create_coordinate_system_impl(
        adapter,
        CreateCoordinateSystemParameters(
            position=[10.0, 20.0, 30.0], rotation=[0.0, 90.0, -90.0]
        ),
    )
    assert result.is_success
    assert result.data.type == "CoordSys"
    use_location, dx, dy, dz, use_rotation, ax, ay, az = calls[0]
    assert use_location is True
    assert (dx, dy, dz) == (0.01, 0.02, 0.03)
    assert use_rotation is True
    assert ax == 0.0
    assert math.isclose(ay, math.pi / 2.0)
    # Negative angles are normalised into [0, 2*pi) as the API requires.
    assert math.isclose(az, 3.0 * math.pi / 2.0)


def test_create_coordinate_system_skips_rotation_when_zero() -> None:
    adapter = _FakeAdapter()
    calls: list[tuple] = []
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            CreateCoordinateSystemUsingNumericalValues=lambda *a: calls.append(a)
            or SimpleNamespace(Name="Coordinate System2")
        ),
    )
    result = reference_geometry._create_coordinate_system_impl(
        adapter, CreateCoordinateSystemParameters(position=[1.0, 0.0, 0.0])
    )
    assert result.is_success
    assert calls[0][4] is False  # UseRotation


def test_create_coordinate_system_guards() -> None:
    adapter = _FakeAdapter()
    no_model = reference_geometry._create_coordinate_system_impl(
        adapter, CreateCoordinateSystemParameters()
    )
    assert no_model.error == "No active model"

    adapter.currentModel = SimpleNamespace()
    bad_vectors = reference_geometry._create_coordinate_system_impl(
        adapter, CreateCoordinateSystemParameters(position=[1.0, 2.0])
    )
    assert "3-element" in (bad_vectors.error or "")


def test_create_coordinate_system_failure_when_returns_none() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = _model(
        FeatureManager=SimpleNamespace(
            CreateCoordinateSystemUsingNumericalValues=lambda *a: None
        ),
    )
    result = reference_geometry._create_coordinate_system_impl(
        adapter, CreateCoordinateSystemParameters(position=[1.0, 2.0, 3.0])
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "Failed to create coordinate system" in (result.error or "")


# ---------------------------------------------------------------------------
# rename_feature
# ---------------------------------------------------------------------------


def test_rename_feature_success_sets_name() -> None:
    adapter = _FakeAdapter()
    feature = SimpleNamespace(Name="Plane1")
    adapter.currentModel = _model(FeatureByName=lambda name: feature)
    result = reference_geometry._rename_feature_impl(
        adapter,
        RenameFeatureParameters(old_name="Plane1", new_name="seat_cyl00"),
    )
    assert result.is_success
    assert feature.Name == "seat_cyl00"  # IFeature.Name was assigned
    assert result.data.name == "seat_cyl00"
    assert result.data.parameters == {
        "old_name": "Plane1",
        "new_name": "seat_cyl00",
    }


def test_rename_feature_strips_document_qualifier_before_lookup() -> None:
    adapter = _FakeAdapter()
    feature = SimpleNamespace(Name="Plane1")
    looked_up: list[str] = []

    def feature_by_name(name):
        looked_up.append(name)
        return feature

    adapter.currentModel = _model(FeatureByName=feature_by_name)
    result = reference_geometry._rename_feature_impl(
        adapter,
        RenameFeatureParameters(old_name="Plane1@drive-train", new_name="base_top"),
    )
    assert result.is_success
    assert looked_up == ["Plane1"]  # "@document" stripped


def test_rename_feature_not_found_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = _model(FeatureByName=lambda name: None)
    result = reference_geometry._rename_feature_impl(
        adapter,
        RenameFeatureParameters(old_name="Nope", new_name="x"),
    )
    assert not result.is_success
    assert "not found" in (result.error or "").lower()


def test_rename_feature_guards_no_model_and_empty_names() -> None:
    adapter = _FakeAdapter()
    no_model = reference_geometry._rename_feature_impl(
        adapter, RenameFeatureParameters(old_name="a", new_name="b")
    )
    assert no_model.error == "No active model"

    adapter.currentModel = _model()
    empty = reference_geometry._rename_feature_impl(
        adapter, RenameFeatureParameters(old_name="", new_name="b")
    )
    assert not empty.is_success
    assert "non-empty" in (empty.error or "")
