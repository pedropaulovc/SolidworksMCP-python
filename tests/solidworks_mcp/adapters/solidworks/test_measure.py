"""Direct branch coverage tests for adapters.solidworks.measure."""

from __future__ import annotations

import math
from types import SimpleNamespace

from solidworks_mcp.adapters.base import (
    AdapterResult,
    AdapterResultStatus,
    MeasureEntityRef,
    MeasureParameters,
)
from solidworks_mcp.adapters.solidworks import measure as measure_module


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


class _FakeMeasure:
    """Measure-tool double; numeric values default to the -1 sentinel."""

    def __init__(self, **values) -> None:
        for prop in measure_module._MEASURE_PROPERTIES:
            setattr(self, prop, -1.0)
        self.IsParallel = False
        self.IsIntersect = False
        self.IsPerpendicular = False
        self.ArcOption = None
        self.calculate_args: list = []
        self.calculate_result = True
        for key, value in values.items():
            setattr(self, key, value)

    def Calculate(self, entities):  # noqa: N802 — COM casing
        self.calculate_args.append(entities)
        return self.calculate_result


def _model(measure_obj, select_results=None):
    """Build a fake model whose Extension records selections."""
    selections: list[tuple] = []
    results = list(select_results) if select_results is not None else None

    def _select(name, entity_type, x, y, z, append, mark, callout, option):
        selections.append((name, entity_type, x, y, z, append))
        if results is None:
            return True
        return results.pop(0)

    model = SimpleNamespace(
        ClearSelection2=lambda flag: True,
        Extension=SimpleNamespace(
            SelectByID2=_select,
            CreateMeasure=lambda: measure_obj,
        ),
    )
    return model, selections


def _measure(adapter, entities, arc_option="center"):
    return measure_module._measure_impl(
        adapter,
        MeasureParameters(entities=entities, arc_option=arc_option),
    )


def test_measure_no_model_errors() -> None:
    adapter = _FakeAdapter()
    result = _measure(adapter, [MeasureEntityRef(entity_type="EDGE", point=[0, 0, 0])])
    assert result.is_error
    assert "No active model" in (result.error or "")


def test_measure_no_entities_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace()
    result = _measure(adapter, [])
    assert result.is_error
    assert "No entities to measure" in (result.error or "")


def test_measure_unknown_arc_option_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel = SimpleNamespace()
    result = _measure(
        adapter,
        [MeasureEntityRef(entity_type="EDGE", point=[0, 0, 0])],
        arc_option="closest",
    )
    assert result.is_error
    assert "Unknown arc_option" in (result.error or "")


def test_measure_edge_by_point_converts_units() -> None:
    """Point goes to SelectByID2 in metres; results come back in mm/deg."""
    adapter = _FakeAdapter()
    tool = _FakeMeasure(Length=0.1, TotalLength=0.1, Angle=math.pi / 2)
    adapter.currentModel, selections = _model(tool)

    result = _measure(
        adapter, [MeasureEntityRef(entity_type="EDGE", point=[25, 25, 50])]
    )

    assert result.is_success
    assert selections == [("", "EDGE", 0.025, 0.025, 0.05, False)]
    assert result.data["length"] == 100.0
    assert result.data["total_length"] == 100.0
    assert result.data["angle"] == 90.0
    # -1 sentinel properties are omitted
    assert "distance" not in result.data
    assert "area" not in result.data
    # boolean flags are always present
    assert result.data["is_parallel"] is False
    assert tool.calculate_args == [None]


def test_measure_face_area_converted_to_mm2() -> None:
    adapter = _FakeAdapter()
    tool = _FakeMeasure(Area=0.0025, Perimeter=0.2)
    adapter.currentModel, _ = _model(tool)

    result = _measure(
        adapter, [MeasureEntityRef(entity_type="FACE", point=[0, 0, 100])]
    )

    assert result.is_success
    assert result.data["area"] == 2500.0
    assert result.data["perimeter"] == 200.0


def test_measure_two_entities_appends_second_selection() -> None:
    adapter = _FakeAdapter()
    tool = _FakeMeasure(Distance=0.05, IsParallel=True)
    adapter.currentModel, selections = _model(tool)

    result = _measure(
        adapter,
        [
            MeasureEntityRef(entity_type="FACE", point=[0, 25, 50]),
            MeasureEntityRef(entity_type="FACE", point=[0, -25, 50]),
        ],
    )

    assert result.is_success
    assert [s[5] for s in selections] == [False, True]
    assert result.data["distance"] == 50.0
    assert result.data["is_parallel"] is True


def test_measure_named_entity_selects_by_name() -> None:
    adapter = _FakeAdapter()
    tool = _FakeMeasure(NormalDistance=0.01)
    adapter.currentModel, selections = _model(tool)

    result = _measure(
        adapter,
        [
            MeasureEntityRef(entity_type="PLANE", name="Front Plane"),
            MeasureEntityRef(entity_type="VERTEX", point=[25, 25, 0]),
        ],
    )

    assert result.is_success
    assert selections[0] == ("Front Plane", "PLANE", 0.0, 0.0, 0.0, False)
    assert selections[1] == ("", "VERTEX", 0.025, 0.025, 0.0, True)
    assert result.data["normal_distance"] == 10.0


def test_measure_arc_option_applied() -> None:
    adapter = _FakeAdapter()
    tool = _FakeMeasure(CenterDistance=0.03)
    adapter.currentModel, _ = _model(tool)

    result = _measure(
        adapter,
        [
            MeasureEntityRef(entity_type="EDGE", point=[25, 0, 0]),
            MeasureEntityRef(entity_type="EDGE", point=[25, 0, 100]),
        ],
        arc_option="maximum",
    )

    assert result.is_success
    assert tool.ArcOption == 2


def test_measure_selection_failure_identifies_entity() -> None:
    adapter = _FakeAdapter()
    tool = _FakeMeasure()
    adapter.currentModel, _ = _model(tool, select_results=[True, False])

    result = _measure(
        adapter,
        [
            MeasureEntityRef(entity_type="FACE", point=[0, 25, 50]),
            MeasureEntityRef(entity_type="EDGE", point=[99, 99, 99]),
        ],
    )

    assert result.is_error
    assert "Failed to select EDGE" in (result.error or "")
    assert "entity 2 of 2" in (result.error or "")


def test_measure_invalid_combination_errors() -> None:
    adapter = _FakeAdapter()
    tool = _FakeMeasure()
    tool.calculate_result = False
    adapter.currentModel, _ = _model(tool)

    result = _measure(adapter, [MeasureEntityRef(entity_type="EDGE", point=[0, 0, 0])])

    assert result.is_error
    assert "invalid combination" in (result.error or "")


def test_measure_null_measure_tool_errors() -> None:
    adapter = _FakeAdapter()
    adapter.currentModel, _ = _model(None)

    result = _measure(adapter, [MeasureEntityRef(entity_type="EDGE", point=[0, 0, 0])])

    assert result.is_error
    assert "Failed to create the measure tool" in (result.error or "")


def test_measure_calculate_falls_back_to_typed_null() -> None:
    """A VT_NULL type mismatch on Calculate(None) retries with a typed null."""

    class _PickyMeasure(_FakeMeasure):
        def Calculate(self, entities):  # noqa: N802
            if entities is None:
                raise TypeError("Type mismatch")
            return super().Calculate(entities)

    adapter = _FakeAdapter()
    tool = _PickyMeasure(Length=0.001)
    adapter.currentModel, _ = _model(tool)

    result = _measure(adapter, [MeasureEntityRef(entity_type="EDGE", point=[0, 0, 0])])

    assert result.is_success
    assert result.data["length"] == 1.0
    assert len(tool.calculate_args) == 1  # the retry, with the typed null


def test_snake_case() -> None:
    assert measure_module._snake_case("Distance") == "distance"
    assert measure_module._snake_case("CenterDistance") == "center_distance"
    assert measure_module._snake_case("DeltaX") == "delta_x"
    assert measure_module._snake_case("IsParallel") == "is_parallel"
