"""Direct branch coverage tests for solidworks_mcp.adapters.solidworks.features."""

from __future__ import annotations

from types import SimpleNamespace

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    CircularPatternParameters,
    DraftParameters,
    ExtrusionParameters,
    LinearPatternParameters,
    MirrorFeatureParameters,
    ShellParameters,
)
from solidworks_mcp.adapters.solidworks import features


class _FakeFeatureAdapter:
    def __init__(self) -> None:
        self.currentModel = None
        self.constants = {
            "swEndCondBlind": 1,
            "swEndCondThroughAll": 2,
            "swStartSketchPlane": 0,
        }
        self._last_sketch_name = None
        self._sketch_count = 2

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

    def _attempt_with_error(self, callback):
        try:
            return callback(), None
        except Exception as exc:
            return None, str(exc)

    def _get_feature_id(self, feature):
        return getattr(feature, "Name", "feature-id")


def test_create_cut_extrude_requires_model() -> None:
    adapter = _FakeFeatureAdapter()
    result = features._create_cut_extrude_impl(adapter, ExtrusionParameters(depth=5.0))
    assert result.status == AdapterResultStatus.ERROR
    assert result.error == "No active model"


def test_create_cut_extrude_collects_all_fallback_errors() -> None:
    adapter = _FakeFeatureAdapter()

    feature_manager = SimpleNamespace(
        FeatureCut4=lambda *args: (_ for _ in ()).throw(RuntimeError("cut4 failed")),
        FeatureCut3=lambda *args: (_ for _ in ()).throw(RuntimeError("cut3 failed")),
    )
    adapter.currentModel = SimpleNamespace(
        FeatureManager=feature_manager,
        ClearSelection2=lambda *_args: True,
        FirstFeature=None,
        Extension=SimpleNamespace(SelectByID2=lambda *args, **kwargs: False),
    )
    adapter._last_sketch_name = "Sketch2"

    result = features._create_cut_extrude_impl(
        adapter,
        ExtrusionParameters(depth=4.0, end_condition="ThroughAll", draft_angle=1.0),
    )

    assert result.status == AdapterResultStatus.ERROR
    assert "FeatureCut4: cut4 failed" in (result.error or "")
    assert "FeatureCut3 modern: cut3 failed" in (result.error or "")
    assert "FeatureCut3 legacy: cut3 failed" in (result.error or "")


def test_create_cut_extrude_uses_modern_fallback_when_cut4_returns_none() -> None:
    adapter = _FakeFeatureAdapter()

    feature = SimpleNamespace(Name="Cut-Extrude9")

    feature_manager = SimpleNamespace(
        FeatureCut4=lambda *args: None,
        FeatureCut3=lambda *args: feature,
    )
    adapter.currentModel = SimpleNamespace(
        FeatureManager=feature_manager,
        ClearSelection2=lambda *_args: True,
        FirstFeature=None,
        Extension=SimpleNamespace(SelectByID2=lambda *args, **kwargs: True),
    )

    result = features._create_cut_extrude_impl(adapter, ExtrusionParameters(depth=6.0))
    assert result.is_success
    assert result.data.type == "Cut-Extrude"
    assert result.data.name == "Cut-Extrude9"


def test_add_fillet_and_chamfer_selection_and_feature_failures() -> None:
    adapter = _FakeFeatureAdapter()

    # Edges are now located by a point on each, and fillet/chamfer call the
    # IModelDoc2-level FeatureFillet3 / FeatureChamfer (not FeatureManager).
    # Selection failure: SelectByID2 returns False -> "Failed to select edge".
    adapter.currentModel = SimpleNamespace(
        Extension=SimpleNamespace(SelectByID2=lambda *a, **k: False),
        ClearSelection2=lambda *_a: True,
        FeatureFillet3=lambda *a: None,
        FeatureChamfer=lambda *a: None,
        FirstFeature=None,
    )

    fillet_select_error = features._add_fillet_impl(adapter, 2.0, [[1.0, 2.0, 3.0]])
    assert fillet_select_error.status == AdapterResultStatus.ERROR
    assert "Failed to select edge" in (fillet_select_error.error or "")

    chamfer_select_error = features._add_chamfer_impl(adapter, 1.0, [[1.0, 2.0, 3.0]])
    assert chamfer_select_error.status == AdapterResultStatus.ERROR
    assert "Failed to select edge" in (chamfer_select_error.error or "")

    # Feature failure: selection succeeds, the COM call returns None, and the
    # feature-tree fallback finds nothing -> "Failed to create ...".
    adapter.currentModel = SimpleNamespace(
        Extension=SimpleNamespace(SelectByID2=lambda *a, **k: True),
        ClearSelection2=lambda *_a: True,
        FeatureFillet3=lambda *a: None,
        FeatureChamfer=lambda *a: None,
        FirstFeature=None,
    )

    fillet_feature_error = features._add_fillet_impl(adapter, 2.0, [[1.0, 2.0, 3.0]])
    assert fillet_feature_error.status == AdapterResultStatus.ERROR
    assert "Failed to create fillet" in (fillet_feature_error.error or "")

    chamfer_feature_error = features._add_chamfer_impl(adapter, 1.0, [[1.0, 2.0, 3.0]])
    assert chamfer_feature_error.status == AdapterResultStatus.ERROR
    assert "Failed to create chamfer" in (chamfer_feature_error.error or "")


def test_add_fillet_requires_model_and_edge_points() -> None:
    adapter = _FakeFeatureAdapter()
    no_model = features._add_fillet_impl(adapter, 2.0, [[0.0, 0.0, 0.0]])
    assert no_model.status == AdapterResultStatus.ERROR
    assert no_model.error == "No active model"

    adapter.currentModel = SimpleNamespace()
    no_edges = features._add_fillet_impl(adapter, 2.0, [])
    assert no_edges.status == AdapterResultStatus.ERROR
    assert "at least one edge point" in (no_edges.error or "")


def test_add_chamfer_requires_model_and_edge_points() -> None:
    adapter = _FakeFeatureAdapter()
    no_model = features._add_chamfer_impl(adapter, 1.0, [[0.0, 0.0, 0.0]])
    assert no_model.status == AdapterResultStatus.ERROR
    assert no_model.error == "No active model"

    adapter.currentModel = SimpleNamespace()
    no_edges = features._add_chamfer_impl(adapter, 1.0, [])
    assert no_edges.status == AdapterResultStatus.ERROR
    assert "at least one edge point" in (no_edges.error or "")


def test_create_cut_extrude_through_all_both_directions() -> None:
    """Through-all + both directions should use the combined end condition."""
    # Exercise the branch that uses swEndCondThroughAllBoth.
    adapter = _FakeFeatureAdapter()

    feature = SimpleNamespace(Name="Cut-Extrude1")
    feature_manager = SimpleNamespace(
        FeatureCut4=lambda *args: feature,
        FeatureCut3=lambda *args: None,
    )
    adapter.currentModel = SimpleNamespace(
        FeatureManager=feature_manager,
        ClearSelection2=lambda *_args: True,
        FirstFeature=None,
        Extension=SimpleNamespace(SelectByID2=lambda *args, **kwargs: True),
    )
    adapter._last_sketch_name = "Sketch1"

    result = features._create_cut_extrude_impl(
        adapter,
        ExtrusionParameters(depth=5.0, end_condition="ThroughAll", both_directions=True),
    )
    assert result.is_success
    assert result.data.type == "Cut-Extrude"


def test_create_cut_extrude_raises_when_no_feature_and_no_errors() -> None:
    """Missing cut feature should raise a generic error when no fallback errors exist."""
    # Force all cut methods to return None without errors to hit the final raise.
    adapter = _FakeFeatureAdapter()

    feature_manager = SimpleNamespace(
        FeatureCut4=lambda *args: None,
        FeatureCut3=lambda *args: None,
    )
    adapter.currentModel = SimpleNamespace(
        FeatureManager=feature_manager,
        ClearSelection2=lambda *_args: True,
        FirstFeature=None,
        Extension=SimpleNamespace(SelectByID2=lambda *args, **kwargs: True),
    )
    adapter._last_sketch_name = "Sketch1"

    result = features._create_cut_extrude_impl(
        adapter,
        ExtrusionParameters(depth=4.0),
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "Failed to create cut extrude feature" in (result.error or "")


# ---------------------------------------------------------------------------
# Phase 2 feature primitives — pywin32 impl success + selection paths
# ---------------------------------------------------------------------------


def _named_feature_model(**extra):
    """Build a fake currentModel whose FeatureByName/Select2 always succeed
    and whose Extension.SelectByID2 always selects (returns True)."""
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


def test_mirror_feature_impl_success() -> None:
    adapter = _FakeFeatureAdapter()
    created = SimpleNamespace(Name="Mirror1")
    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(InsertMirrorFeature2=lambda *a: created),
    )
    result = features._mirror_feature_impl(
        adapter,
        MirrorFeatureParameters(plane="Right Plane", features=["Boss-Extrude1"]),
    )
    assert result.is_success
    assert result.data.type == "Mirror"
    assert result.data.name == "Mirror1"


def test_mirror_feature_impl_guards() -> None:
    adapter = _FakeFeatureAdapter()
    no_model = features._mirror_feature_impl(
        adapter, MirrorFeatureParameters(plane="Right Plane", features=["F1"])
    )
    assert no_model.error == "No active model"

    adapter.currentModel = SimpleNamespace()
    no_feats = features._mirror_feature_impl(
        adapter, MirrorFeatureParameters(plane="Right Plane", features=[])
    )
    assert "at least one feature" in (no_feats.error or "")


def test_circular_pattern_impl_success() -> None:
    adapter = _FakeFeatureAdapter()
    created = SimpleNamespace(Name="CircPattern1")
    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=lambda *a: created),
    )
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(
            axis_point=[0.0, 0.0, 10.0], features=["Cut-Extrude1"], count=6
        ),
    )
    assert result.is_success
    assert result.data.type == "CircularPattern"
    assert result.data.parameters["count"] == 6


def test_circular_pattern_impl_geometry_pattern_forwarded() -> None:
    adapter = _FakeFeatureAdapter()
    created = SimpleNamespace(Name="CircPattern1")
    captured: list[tuple] = []

    def _capture(*args):
        captured.append(args)
        return created

    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=_capture),
    )
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(
            axis_point=[0.0, 0.0, 10.0],
            features=["Cut-Extrude1"],
            count=6,
            geometry_pattern=True,
        ),
    )
    assert result.is_success
    assert result.data.parameters["geometry_pattern"] is True
    # FeatureCircularPattern5 arg 5 is GeometryPattern.
    assert captured[0][4] is True


def test_circular_pattern_impl_axis_selection_failure() -> None:
    adapter = _FakeFeatureAdapter()
    adapter.currentModel = _named_feature_model(
        Extension=SimpleNamespace(SelectByID2=lambda *a, **k: False),
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=lambda *a: object()),
    )
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(
            axis_point=[1.0, 2.0, 3.0], features=["Cut-Extrude1"], count=4
        ),
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "Failed to select rotation axis" in (result.error or "")


def test_linear_pattern_impl_success() -> None:
    adapter = _FakeFeatureAdapter()
    created = SimpleNamespace(Name="LPattern1")
    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(FeatureLinearPattern5=lambda *a: created),
    )
    result = features._linear_pattern_impl(
        adapter,
        LinearPatternParameters(
            direction_point=[50.0, 0.0, 0.0],
            features=["Cut-Extrude1"],
            count=4,
            spacing=20.0,
        ),
    )
    assert result.is_success
    assert result.data.type == "LinearPattern"
    assert result.data.parameters["spacing"] == 20.0


def test_shell_impl_success_recovers_feature_by_diff() -> None:
    # InsertFeatureShell returns void; the feature is recovered by diffing the
    # tree against the names captured before the call. The fake appends the
    # shell feature only when InsertFeatureShell runs, so the diff finds it.
    adapter = _FakeFeatureAdapter()
    shell_feat = SimpleNamespace(Name="Shell1", GetNextFeature=lambda: None)
    model = _named_feature_model(FirstFeature=None)

    def _insert(thickness, outward):
        model.FirstFeature = shell_feat  # SW appends the new feature
        return None

    model.InsertFeatureShell = _insert
    adapter.currentModel = model
    result = features._shell_impl(
        adapter, ShellParameters(thickness=2.0, face_points=[[0.0, 0.0, 100.0]])
    )
    assert result.is_success
    assert result.data.type == "Shell"
    assert result.data.name == "Shell1"


def test_shell_impl_face_selection_failure() -> None:
    adapter = _FakeFeatureAdapter()
    adapter.currentModel = _named_feature_model(
        Extension=SimpleNamespace(SelectByID2=lambda *a, **k: False),
        InsertFeatureShell=lambda thickness, outward: None,
    )
    result = features._shell_impl(
        adapter, ShellParameters(thickness=2.0, face_points=[[0.0, 0.0, 100.0]])
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "Failed to select face" in (result.error or "")


def test_draft_impl_success() -> None:
    adapter = _FakeFeatureAdapter()
    created = SimpleNamespace(Name="Draft1")
    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(InsertMultiFaceDraft=lambda *a: created),
    )
    result = features._draft_impl(
        adapter,
        DraftParameters(
            angle=3.0, neutral_plane="Top Plane", face_points=[[25.0, 0.0, 50.0]]
        ),
    )
    assert result.is_success
    assert result.data.type == "Draft"
    assert result.data.parameters["neutral_plane"] == "Top Plane"


def test_draft_impl_requires_model_and_faces() -> None:
    adapter = _FakeFeatureAdapter()
    no_model = features._draft_impl(
        adapter,
        DraftParameters(angle=3.0, neutral_plane="Top Plane", face_points=[[0, 0, 0]]),
    )
    assert no_model.error == "No active model"
