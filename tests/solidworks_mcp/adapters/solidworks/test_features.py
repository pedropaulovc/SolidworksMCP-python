"""Direct branch coverage tests for solidworks_mcp.adapters.solidworks.features."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    CircularPatternParameters,
    DraftParameters,
    ExtrusionParameters,
    LinearPatternParameters,
    MirrorFeatureParameters,
    ShellParameters,
    SweepParameters,
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

    # Edges are now located by a point on each. Fillet calls the IModelDoc2-level
    # FeatureFillet3; chamfer calls FeatureManager.InsertFeatureChamfer (so it can
    # take whole faces + tangent propagation, which the 3-arg form cannot).
    # Selection failure: SelectByID2 returns False -> "Failed to select edge".
    adapter.currentModel = SimpleNamespace(
        Extension=SimpleNamespace(SelectByID2=lambda *a, **k: False),
        ClearSelection2=lambda *_a: True,
        FeatureFillet3=lambda *a: None,
        FeatureManager=SimpleNamespace(InsertFeatureChamfer=lambda *a: None),
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
        FeatureManager=SimpleNamespace(InsertFeatureChamfer=lambda *a: None),
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
    assert "at least one edge or face point" in (no_edges.error or "")


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


class _CreationFeatureDispatch:
    """A named native-feature double, distinct from the ordinary model/manager."""

    def __init__(self, name, type_name, *, falsey=False):
        self.Name = name
        self.type_name = type_name
        self.falsey = falsey
        self.truth_tests = 0

    def GetTypeName2(self):
        return self.type_name

    def __bool__(self):
        self.truth_tests += 1
        if self.falsey:
            return False
        raise AssertionError("A non-null creation dispatch must not be truth-tested")


@pytest.mark.parametrize("null_result", [False, True])
def test_create_sweep_impl_checks_only_null_result(monkeypatch, null_result) -> None:
    adapter = _FakeFeatureAdapter()
    created = _CreationFeatureDispatch("Sweep1", "Sweep")
    calls = []

    def _sweep(*args):
        calls.append(args)
        return None if null_result else created

    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(InsertProtrusionSwept4=_sweep),
    )
    monkeypatch.setattr(
        features, "_profile_feature_names", lambda _adapter: ["Profile", "Path"]
    )
    result = features._create_sweep_impl(adapter, SweepParameters(path="Path"))
    assert len(calls) == 1
    assert created.truth_tests == 0
    if null_result:
        assert result.status == AdapterResultStatus.ERROR
        assert result.error == "Failed to create sweep feature"
    else:
        assert result.is_success, result.error
        assert result.data.name == "Sweep1"
        assert result.data.id == "Sweep1"
        assert result.data.type == "Sweep"
        assert result.data.parameters["profile"] == "Profile"
        assert result.data.parameters["path"] == "Path"


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


@pytest.mark.parametrize("falsey", [False, True])
def test_circular_pattern_impl_keeps_non_null_native_return(
    monkeypatch, falsey
) -> None:
    adapter = _FakeFeatureAdapter()
    created = _CreationFeatureDispatch("CircPattern1", "CirPattern", falsey=falsey)
    calls = []
    reconciled = []

    def _pattern(*args):
        calls.append(args)
        return created

    def _added_features(_adapter, _before):
        reconciled.append(True)
        if falsey:
            return []  # Falling back would wrongly report absence.
        raise AssertionError("A named non-null return must not use tree fallback")

    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=_pattern),
    )
    monkeypatch.setattr(features, "_added_features", _added_features)
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(
            axis_name="Axis1", features=["Cut-Extrude1"], count=6
        ),
    )
    assert result.is_success, result.error
    assert len(calls) == 1
    assert reconciled == []
    assert created.truth_tests == 0
    assert result.data.name == "CircPattern1"
    assert result.data.id == "CircPattern1"
    assert result.data.type == "CircularPattern"
    assert result.data.parameters["count"] == 6


@pytest.mark.parametrize("falsey", [False, True])
def test_circular_pattern_impl_null_return_recovers_non_null_dispatch(
    monkeypatch, falsey
) -> None:
    adapter = _FakeFeatureAdapter()
    created = _CreationFeatureDispatch("CircPattern1", "CirPattern", falsey=falsey)
    calls = []
    reconciled = []

    def _pattern(*args):
        calls.append(args)
        return None

    def _added_features(actual_adapter, before):
        assert actual_adapter is adapter
        assert before.names == frozenset()
        reconciled.append(before)
        return [(created.Name, created)]

    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=_pattern),
    )
    # Bound only tree enumeration; keep the real resolver, type matching and
    # raw-to-feature binding so the post-reconciliation guard is exercised.
    monkeypatch.setattr(features, "_added_features", _added_features)
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(
            axis_name="Axis1", features=["Cut-Extrude1"], count=6
        ),
    )
    assert result.is_success, result.error
    assert len(calls) == 1
    assert len(reconciled) == 1
    assert created.truth_tests == 0
    assert result.data.name == "CircPattern1"
    assert result.data.id == "CircPattern1"
    assert result.data.type == "CircularPattern"
    assert result.data.parameters["count"] == 6


def test_circular_pattern_impl_null_without_added_feature_errors() -> None:
    adapter = _FakeFeatureAdapter()
    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=lambda *a: None),
    )
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(
            axis_name="Axis1", features=["Cut-Extrude1"], count=6
        ),
    )
    assert result.status == AdapterResultStatus.ERROR
    assert result.error == "Failed to create circular pattern"


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


def test_circular_pattern_impl_axis_name_selects_by_name() -> None:
    adapter = _FakeFeatureAdapter()
    created = SimpleNamespace(Name="CircPattern1")
    looked_up: list[str] = []

    def _feature_by_name(name):
        looked_up.append(name)
        return SimpleNamespace(Select2=lambda append, mark: True)

    adapter.currentModel = _named_feature_model(
        FeatureByName=_feature_by_name,
        # Point selection must NOT be consulted when axis_name is given.
        Extension=SimpleNamespace(
            SelectByID2=lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("axis_point path used despite axis_name")
            )
        ),
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=lambda *a: created),
    )
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(
            axis_name="Axis1", features=["Cut-Extrude1"], count=24
        ),
    )
    assert result.is_success
    assert result.data.parameters["axis_name"] == "Axis1"
    assert result.data.parameters["axis_entity"] == "AXIS"
    assert "Axis1" in looked_up


def test_circular_pattern_impl_axis_name_lookup_failure() -> None:
    adapter = _FakeFeatureAdapter()
    adapter.currentModel = _named_feature_model(
        FeatureByName=lambda name: None,
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=lambda *a: object()),
    )
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(axis_name="Nope", features=["F1"], count=4),
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "Failed to select rotation axis by name" in (result.error or "")


def test_circular_pattern_impl_requires_axis_reference() -> None:
    adapter = _FakeFeatureAdapter()
    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(FeatureCircularPattern5=lambda *a: object()),
    )
    result = features._circular_pattern_impl(
        adapter,
        CircularPatternParameters(features=["F1"], count=4),
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "axis_name or axis_point" in (result.error or "")


class _FakeEdge:
    """A body edge from ``start`` to ``end`` (mm). ``line=False`` stands in for a
    curved edge (an S-curve) whose ends and chord midpoint lie on the chord."""

    def __init__(self, start, end, line=True):
        self.start = [c / 1000.0 for c in start]
        self.end = [c / 1000.0 for c in end]
        self.line = line
        self.selected = None

    def GetCurve(self):
        return SimpleNamespace(IsLine=lambda: self.line)

    def GetCurveParams2(self):
        return (*self.start, *self.end, 0.0, 1.0, 0.0, 0.0, 0.0)

    def GetClosestPointOn(self, x, y, z):
        chord = [e - s for s, e in zip(self.start, self.end)]
        length2 = sum(c * c for c in chord)
        rel = [p - s for p, s in zip((x, y, z), self.start)]
        t = min(1.0, max(0.0, sum(r * c for r, c in zip(rel, chord)) / length2))
        return tuple(s + t * c for s, c in zip(self.start, chord)) + (t, 0.0)

    def Select2(self, append, mark):
        self.selected = (append, mark)
        return True


def _rack_pattern(
    chosen, face_count, count=101, vector=(1.0, 0.0, 0.0), delete_ok=True
):
    """The platen-rack ToothPattern call (point on the bar's bottom-back edge).

    The body also has edges that must NOT be chosen: one through the point but
    along Y, a curved one nearer the point whose chord runs along X, and a
    parallel straight edge farther away than ``chosen``. Returns the result,
    the ``FeatureLinearPattern5`` arguments, and what was deleted.
    """
    adapter = _FakeFeatureAdapter()
    decoys = [
        _FakeEdge((134.82, 0.0, 0.0), (134.82, 12.0, 0.0)),
        _FakeEdge((100.0, 0.0, 1.0), (170.0, 0.0, 1.0), line=False),
        _FakeEdge((269.64, 12.0, 0.0), (2.2139, 12.0, 0.0)),
    ]
    edges = [*decoys, chosen]
    calls = []
    deleted = []
    selection = []
    created = SimpleNamespace(
        Name="LPattern1",
        GetFaces=lambda: tuple(object() for _ in range(face_count)),
        Select2=lambda append, mark: selection.append("LPattern1") or True,
    )

    def _pattern(*args):
        calls.append(args)
        return created

    def _delete(_options):
        deleted.extend(selection)
        return delete_ok

    def _selected():
        return next(edge for edge in edges if edge.selected)

    adapter.currentModel = _named_feature_model(
        FeatureManager=SimpleNamespace(FeatureLinearPattern5=_pattern),
        GetBodies2=lambda *_a: [SimpleNamespace(GetEdges=lambda: edges)],
        Extension=SimpleNamespace(
            SelectByID2=lambda *a, **k: True, DeleteSelection2=_delete
        ),
        SelectionManager=SimpleNamespace(
            GetSelectedObjectType3=lambda index, mark: 1,  # swSelEDGES
            GetSelectedObject6=lambda index, mark: _selected(),
        ),
    )
    result = features._linear_pattern_impl(
        adapter,
        LinearPatternParameters(
            direction_point=[134.82, 0.0, 0.0],
            direction_vector=list(vector),
            features=["SeedGap"],
            count=count,
            spacing=2.65988,
        ),
    )
    assert all(edge.selected is None for edge in decoys)
    return result, calls, deleted


@pytest.mark.parametrize(
    ("start", "end", "vector", "flip"),
    [
        # Measured live: the pattern marches along the edge's start->end sense
        # unless FlipDir1 reverses it; a -X edge with FlipDir1=False sent all
        # 100 rack gaps off the bar.
        ((269.64, 0.0, 6.0), (0.0, 0.0, 6.0), (1.0, 0.0, 0.0), True),
        ((0.0, 0.0, 6.0), (269.64, 0.0, 6.0), (1.0, 0.0, 0.0), False),
        ((0.0, 0.0, 6.0), (269.64, 0.0, 6.0), (-2.0, 0.0, 0.0), True),
    ],
)
def test_linear_pattern_impl_sets_flip_from_edge_sense(start, end, vector, flip) -> None:
    chosen = _FakeEdge(start, end)
    result, calls, _ = _rack_pattern(chosen, face_count=300, vector=vector)
    assert result.is_success, result.error
    assert chosen.selected == (True, 1)
    assert calls[0][4] is flip  # FlipDir1
    assert result.data.parameters["flip_direction"] is flip


def test_linear_pattern_impl_rejects_and_deletes_pattern_whose_instances_all_missed() -> None:
    # SolidWorks still returns a pattern whose every instance missed the body;
    # farm build 7 only noticed a step later, as a bare volume mismatch.
    result, _, deleted = _rack_pattern(
        _FakeEdge((269.64, 0.0, 6.0), (0.0, 0.0, 6.0)), face_count=0
    )
    assert result.status == AdapterResultStatus.ERROR
    error = result.error or ""
    assert "LPattern1" in error
    assert "none of the 100 instances" in error
    assert "EDGE (269.640,0.000,6.000)->(0.000,0.000,6.000) mm" in error
    assert "FlipDir1=True" in error
    assert deleted == ["LPattern1"]
    assert "the pattern was deleted" in error


def test_linear_pattern_impl_reports_void_pattern_it_could_not_delete() -> None:
    result, _, _ = _rack_pattern(
        _FakeEdge((269.64, 0.0, 6.0), (0.0, 0.0, 6.0)), face_count=0, delete_ok=False
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "deleting the pattern FAILED, so it is still in the model" in (
        result.error or ""
    )


def test_linear_pattern_impl_accepts_pattern_whose_instances_landed() -> None:
    result, calls, deleted = _rack_pattern(
        _FakeEdge((0.0, 0.0, 6.0), (269.64, 0.0, 6.0)), face_count=300
    )
    assert result.is_success, result.error
    assert result.data.name == "LPattern1"
    assert calls[0][:2] == (101, pytest.approx(0.00265988))
    assert result.data.parameters["instance_faces"] == 300
    assert deleted == []
    assert result.data.parameters["direction"] == (
        "EDGE (0.000,0.000,6.000)->(269.640,0.000,6.000) mm"
    )


def test_linear_pattern_impl_single_instance_owns_no_faces() -> None:
    # count == 1 is the seed alone: no instance, so no faces is correct.
    result, _, _ = _rack_pattern(
        _FakeEdge((0.0, 0.0, 6.0), (269.64, 0.0, 6.0)), face_count=0, count=1
    )
    assert result.is_success, result.error


def test_linear_pattern_impl_errors_when_no_edge_runs_along_vector() -> None:
    result, calls, _ = _rack_pattern(
        _FakeEdge((0.0, 0.0, 6.0), (269.64, 0.0, 6.0)),
        face_count=300,
        vector=(0.0, 0.0, 1.0),
    )
    assert result.status == AdapterResultStatus.ERROR
    assert "No straight body edge runs along" in (result.error or "")
    assert calls == []


def test_shell_impl_success_recovers_feature_by_diff() -> None:
    # InsertFeatureShell returns void; the feature is recovered by diffing the
    # tree against the names captured before the call. The fake appends the
    # shell feature only when InsertFeatureShell runs, so the diff finds it.
    adapter = _FakeFeatureAdapter()
    shell_feat = SimpleNamespace(
        Name="Shell1", GetTypeName2="Shell", GetNextFeature=lambda: None
    )
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
