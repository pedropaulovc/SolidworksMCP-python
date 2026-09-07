"""Drawing helper behavior with explicit native-boundary doubles, never COM."""

from types import SimpleNamespace as NS
from unittest.mock import Mock, call

import pytest

from solidworks_mcp.adapters.solidworks import drawing as d


class Adapter:
    """Only the synchronous adapter utility contract used by these helpers."""

    def __init__(self, model=None, app=None):
        self.currentModel = model
        self.swApp = app

    @staticmethod
    def _attempt(callback, default=None):
        try:
            return callback()
        except Exception:
            return default

    @staticmethod
    def _get_attr_or_call(obj, name):
        member = getattr(obj, name, None)
        return member() if callable(member) else member


@pytest.fixture(autouse=True)
def native_boundary(monkeypatch):
    """Forbid typelib discovery; all document handles belong to this unit test."""
    for name in ("early_bound", "early_bound_or_flag", "flagged"):
        monkeypatch.setattr(d._sw_type_info, name, lambda obj, *_: obj)
    monkeypatch.setattr(d, "double_array", lambda values: ("R8", tuple(values)))
    monkeypatch.setattr(d, "null_callout", lambda: "NULL_DISPATCH")


def model(**members):
    """Explicit common document operations, with caller-supplied native results."""
    defaults = {
        "ClearSelection2": Mock(),
        "EditRebuild3": Mock(),
        "ForceRebuild3": Mock(),
    }
    return NS(**(defaults | members))


def dimension(name="Bore", value=0.008, kind=6, selected=True):
    """Keep annotation, display and model parameter identities distinct."""
    parameter = NS(
        Name=name,
        FullName=f"{name}@Sketch@Part",
        SystemValue=value,
        SetToleranceType=Mock(return_value=True),
        SetToleranceValues=Mock(),
    )
    display = NS(Type2=kind, GetDimension=Mock(return_value=parameter), SetText=Mock())
    annotation = NS(
        GetSpecificAnnotation=Mock(return_value=display),
        Select2=Mock(return_value=selected),
        SetPosition=Mock(),
    )
    return annotation, display, parameter


def test_missing_current_drawing_fails_before_any_operation():
    with pytest.raises(RuntimeError, match="No active drawing"):
        d.set_units_mm(Adapter())


@pytest.mark.parametrize(
    "mode", ["explicit", "configured", "sibling", "missing", "disconnected", "rejected"]
)
def test_new_drawing_resolves_owned_template_and_preserves_old_handle_on_failure(
    tmp_path, mode
):
    template = tmp_path / "project.drwdot"
    part = tmp_path / "part.prtdot"
    if mode != "missing":
        template.write_bytes(b"template")
    prior, created = object(), object()
    app = NS(
        GetUserPreferenceStringValue=Mock(
            side_effect=lambda slot: (
                str(template) if slot == 10 and mode != "sibling" else str(part)
            )
        ),
        NewDocument=Mock(return_value=None if mode == "rejected" else created),
    )
    adapter = Adapter(prior, None if mode == "disconnected" else app)
    if mode in {"missing", "disconnected", "rejected"}:
        with pytest.raises(RuntimeError, match="template|connected|NewDocument"):
            d.new_drawing(adapter)
        assert adapter.currentModel is prior
        return
    supplied = str(template) if mode == "explicit" else None
    assert d.new_drawing(adapter, template=supplied, width=0.4, height=0.3) is created
    assert adapter.currentModel is created
    app.NewDocument.assert_called_once_with(str(template.resolve()), 12, 0.4, 0.3)
    if mode == "explicit":
        app.GetUserPreferenceStringValue.assert_not_called()


def test_unavailable_explicit_template_uses_resolved_seat_template(tmp_path, caplog):
    target = tmp_path / "drawing.drwdot"
    target.write_bytes(b"template")
    app = NS(
        GetUserPreferenceStringValue=Mock(return_value=str(target)),
        NewDocument=Mock(return_value=object()),
    )
    d.new_drawing(Adapter(app=app), template=str(tmp_path / "missing.drwdot"))
    assert "not found" in caplog.text
    assert app.NewDocument.call_args.args[0] == str(target)


@pytest.mark.parametrize("language", ["english", "german", "missing", "no_part"])
def test_sheet_format_resolution_checks_real_files(tmp_path, language):
    part = tmp_path / "templates/part.prtdot"
    target = tmp_path / f"lang/{language}/sheetformat/custom.slddrt"
    if language not in {"missing", "no_part"}:
        target.parent.mkdir(parents=True)
        target.write_bytes(b"format")
    adapter = Adapter(
        app=NS(
            GetUserPreferenceStringValue=Mock(
                return_value=None if language == "no_part" else str(part)
            )
        )
    )
    assert d.resolve_sheet_format(adapter, "custom.slddrt") == (
        str(target) if target.exists() else ""
    )


@pytest.mark.parametrize("state", ["normal", "missing_path", "missing_sheet"])
def test_apply_sheet_format_retains_notes_and_returns_native_result(tmp_path, state):
    target = tmp_path / "format.slddrt"
    if state != "missing_path":
        target.write_bytes(b"format")
    sheet = NS(SetTemplateName=Mock(), ReloadTemplate=Mock(return_value=4))
    doc = model(
        GetCurrentSheet=Mock(return_value=None if state == "missing_sheet" else sheet)
    )
    result = d.apply_sheet_format(Adapter(doc), str(target), keep_notes=False)
    if state != "normal":
        assert result == -1
        sheet.ReloadTemplate.assert_not_called()
        return
    assert result == 4
    sheet.SetTemplateName.assert_called_once_with(str(target))
    sheet.ReloadTemplate.assert_called_once_with(False)
    assert sheet.SheetFormatVisible is True
    doc.ForceRebuild3.assert_called_once_with(False)


@pytest.mark.parametrize("paper,expected", [(2, 2), (13, 12)])
@pytest.mark.parametrize("accepted", [True, False])
def test_sheet_setup_uses_requested_size_projection_link_and_rebuild(
    paper, expected, accepted
):
    doc = model(
        GetCurrentSheet=NS(GetName="Sheet 1"), SetupSheet6=Mock(return_value=accepted)
    )
    assert (
        d.setup_sheet(
            Adapter(doc),
            template=paper,
            scale=(2, 3),
            first_angle=True,
            property_view="front",
            paper_width=0.4,
            paper_height=0.3,
        )
        is accepted
    )
    doc.SetupSheet6.assert_called_once_with(
        "Sheet 1",
        expected,
        paper,
        2.0,
        3.0,
        True,
        "",
        0.4,
        0.3,
        "front",
        False,
        0.0,
        0.0,
        0.0,
        0.0,
        0,
        0,
    )
    doc.ForceRebuild3.assert_called_once_with(False)


def test_custom_property_reads_use_explicit_source_not_current_drawing():
    source = NS(GetCustomInfoValue=Mock(side_effect=["Steel", "", 7]))
    current = NS(GetCustomInfoValue=Mock(side_effect=AssertionError("wrong owner")))
    assert d.read_custom_properties(
        Adapter(current), ["Material", "Blank", "Bad"], model=source
    ) == {"Material": "Steel"}
    assert source.GetCustomInfoValue.call_args_list == [
        call("", "Material"),
        call("", "Blank"),
        call("", "Bad"),
    ]
    current.GetCustomInfoValue.assert_not_called()


def test_units_request_exact_metric_preset_length_and_precision():
    doc = model(SetUserPreferenceIntegerValue=Mock())
    d.set_units_mm(Adapter(doc), decimals=3)
    assert doc.SetUserPreferenceIntegerValue.call_args_list == [
        call(263, 5),
        call(47, 0),
        call(49, 3),
    ]


@pytest.mark.parametrize(
    "raw,expected",
    [(None, None), ([1, 2], None), ([1, 2, 3, 4, 5], (1.0, 2.0, 3.0, 4.0))],
)
def test_view_outline_requires_four_values(raw, expected):
    assert d.view_outline(Adapter(), NS(GetOutline=Mock(return_value=raw))) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("bad", None),
        ((1,), None),
        ((1, 0), None),
        ((2, 1), (2, 1)),
        ((1, 4), (1, 4)),
        ((1.2, 1), (1.2, 1.0)),
        ((1, 1.2), (1.0, 1.2)),
        ((0, 1), (0.0, 1.0)),
    ],
)
def test_view_scale_uses_native_ratio_not_displayed_value(raw, expected):
    assert d.get_view_scale(Adapter(), NS(ScaleRatio=raw)) == expected
    assert d.format_scale(expected) == (
        f"{expected[0]}:{expected[1]}" if expected else "NTS"
    )


def test_view_names_accept_only_native_strings():
    adapter = Adapter()
    assert (
        d.orientation_name(adapter, NS(GetOrientationName=lambda: "*Front")) == "*Front"
    )
    assert d.orientation_name(adapter, NS(GetOrientationName=1)) == ""
    assert d.view_name(adapter, NS(GetName2=lambda: "front")) == "front"
    assert d.view_name(adapter, NS(GetName2=None)) == ""


@pytest.mark.parametrize("accepted", [True, False])
def test_view_move_uses_typed_xy_and_requested_child_policy(accepted):
    doc = model()
    view = NS(SetViewPosition=Mock(return_value=accepted))
    assert (
        d.set_view_position(Adapter(doc), view, 0.12, 0.15, move_children=False)
        is accepted
    )
    view.SetViewPosition.assert_called_once_with(("R8", (0.12, 0.15)), False)
    doc.EditRebuild3.assert_called_once_with()


@pytest.mark.parametrize("scale", [None, (3, 2)])
def test_place_view_returns_exact_handle_and_optional_typed_scale(scale):
    view = NS()
    doc = model(CreateDrawViewFromModelView3=Mock(return_value=view))
    assert (
        d.place_view(Adapter(doc), "part.SLDPRT", "*Front", 0.1, 0.2, scale=scale)
        is view
    )
    doc.CreateDrawViewFromModelView3.assert_called_once_with(
        "part.SLDPRT", "*Front", 0.1, 0.2, 0.0
    )
    assert getattr(view, "ScaleRatio", None) == (("R8", (3.0, 2.0)) if scale else None)


def test_rejected_view_creation_is_not_a_usable_view():
    with pytest.raises(RuntimeError, match="CreateDrawViewFromModelView3 failed"):
        d.place_view(
            Adapter(model(CreateDrawViewFromModelView3=Mock(return_value=None))),
            "part",
            "*Top",
            0.1,
            0.2,
        )


@pytest.mark.parametrize(
    "angle,method", [(True, "Create1stAngleViews2"), (False, "Create3rdAngleViews2")]
)
@pytest.mark.parametrize("accepted", [True, False])
def test_standard_view_projection_routes_to_exact_native_method(
    angle, method, accepted
):
    create = Mock(return_value=accepted)
    assert (
        d.create_standard_views(
            Adapter(model(**{method: create})), "part", first_angle=angle
        )
        is accepted
    )
    create.assert_called_once_with("part")


def test_delete_view_clears_selection_selects_named_view_then_rebuilds():
    select = Mock(return_value=True)
    doc = model(Extension=NS(SelectByID2=select), EditDelete=Mock(return_value=True))
    assert d.delete_view(Adapter(doc), NS(GetName2="front"))
    select.assert_called_once_with(
        "front", "DRAWINGVIEW", 0.0, 0.0, 0.0, False, 0, "NULL_DISPATCH", 0
    )
    doc.EditDelete.assert_called_once_with()
    doc.EditRebuild3.assert_called_once_with()


@pytest.mark.parametrize(
    "marked,holes,expected", [(True, False, 0x28000), (False, True, 0x1A8000)]
)
@pytest.mark.parametrize("result", [None, "invalid", ("ann1", "ann2")])
def test_import_dimensions_selects_owner_and_hole_location_mask(
    marked, holes, expected, result
):
    ext = NS(SelectByID2=Mock(return_value=True))
    doc = model(
        Extension=ext,
        ActivateView=Mock(),
        InsertModelAnnotations3=Mock(return_value=result),
    )
    actual = d.insert_model_dims(
        Adapter(doc),
        NS(GetName2="front"),
        marked_only=marked,
        hole_callouts=holes,
        all_views=True,
    )
    assert actual == (list(result) if isinstance(result, tuple) else [])
    doc.ActivateView.assert_called_once_with("front")
    doc.InsertModelAnnotations3.assert_called_once_with(
        0, expected, True, True, False, False
    )
    assert ext.SelectByID2.call_args.args[0:2] == ("front", "DRAWINGVIEW")


def test_hole_callout_grouping_keeps_linear_and_unreadable_dimensions_separate():
    first, disp, _ = dimension()
    duplicate, duplicate_disp, _ = dimension()
    linear, linear_disp, _ = dimension(kind=2)
    unreadable, unreadable_disp, _ = dimension(value="unreadable")
    doc = model(EditDelete=Mock())
    assert (
        d.annotate_holes_thru(Adapter(doc), [first, duplicate, linear, unreadable]) == 2
    )
    assert disp.SetText.call_args_list == [
        call(0, "2X <MOD-DIAM>8.00"),
        call(4, "THRU"),
    ]
    duplicate.Select2.assert_called_once_with(False, 0)
    duplicate_disp.SetText.assert_not_called()
    linear_disp.SetText.assert_not_called()
    unreadable_disp.SetText.assert_called_once_with(4, "THRU")
    doc.EditDelete.assert_called_once_with()


@pytest.mark.parametrize("consolidate,expected", [(True, 1), (False, 2)])
def test_thread_callout_uses_system_meters_and_sets_complete_text(
    consolidate, expected
):
    first, first_disp, _ = dimension(value=0.0025)
    second, _, _ = dimension(value=0.0025)
    doc = model(EditDelete=Mock())
    assert (
        d.annotate_holes_thru(
            Adapter(doc),
            [first, second],
            consolidate=consolidate,
            thread_map={2.5: "M3X0.5"},
        )
        == expected
    )
    assert first_disp.SetText.call_args_list == [
        call(0, "2X M3X0.5" if consolidate else "M3X0.5"),
        call(4, "THRU"),
    ]


def test_dimension_names_come_from_parameter_identity_and_curation_preserves_unmatched():
    removed, _, _ = dimension("Extra")
    kept, _, _ = dimension("Bore")
    unknown = NS(GetSpecificAnnotation=Mock(return_value=None))
    doc = model(EditDelete=Mock())
    adapter = Adapter(doc)
    assert d.dimension_name(adapter, kept) == "Bore"
    assert d.dimension_full_name(adapter, kept) == "Bore@Sketch@Part"
    assert (
        d.dimension_name(adapter, unknown)
        == d.dimension_full_name(adapter, unknown)
        == ""
    )
    assert d.curate_dimensions(
        adapter,
        [removed, kept, unknown],
        delete=("Extra",),
        reposition={"Bore": (0.1, 0.2)},
    ) == [kept, unknown]
    kept.SetPosition.assert_called_once_with(0.1, 0.2, 0.0)
    removed.Select2.assert_called_once_with(False, 0)
    doc.EditRebuild3.assert_called_once_with()


@pytest.mark.parametrize("vertical", [True, False])
@pytest.mark.parametrize("selection", ["accepted", "rejected"])
def test_overall_dimension_requires_both_edges_before_insertion(vertical, selection):
    output = object()
    select = Mock(side_effect=[True, selection == "accepted"])
    doc = model(
        Extension=NS(SelectByID2=select),
        ActivateView=Mock(),
        AddDimension2=Mock(return_value=output),
    )
    view = NS(GetName2="front", GetOutline=lambda: (0.0, 0.0, 0.1, 0.2))
    result = d.add_overall_dimension(Adapter(doc), view, vertical=vertical, offset=0.01)
    assert [call.args[5] for call in select.call_args_list] == [False, True]
    if selection == "rejected":
        assert result is None
        doc.AddDimension2.assert_not_called()
        return
    assert result is output
    doc.AddDimension2.assert_called_once_with(
        *((-0.01, 0.1, 0.0) if vertical else (0.05, -0.01, 0.0))
    )


def test_third_angle_symbol_scales_sheet_coordinates_and_restores_default_layer():
    sketch = NS(CreateCircle=Mock(), CreateLine=Mock())
    sheet = NS(GetName="Sheet1", GetProperties=lambda: (2, 2, 2, 1))
    doc = model(
        SketchManager=sketch,
        GetCurrentSheet=lambda: sheet,
        ActivateSheet=Mock(),
        CreateLayer2=Mock(),
        SetCurrentLayer=Mock(),
    )
    assert d.add_third_angle_symbol(Adapter(doc), 0.1, 0.2, size=0.01)
    assert [entry.args for entry in sketch.CreateCircle.call_args_list] == [
        pytest.approx((0.05, 0.1, 0.0, 0.055, 0.1, 0.0)),
        pytest.approx((0.05, 0.1, 0.0, 0.0525, 0.1, 0.0)),
    ]
    assert sketch.CreateLine.call_count == 5
    first, second = [entry.args for entry in sketch.CreateLine.call_args_list[:2]]
    assert first[0] < second[0]
    assert first[4] - first[1] == pytest.approx((second[4] - second[1]) / 2)
    assert doc.SetCurrentLayer.call_args_list == [call("PROJECTION"), call("")]
    doc.ActivateSheet.assert_called_once_with("Sheet1")


@pytest.mark.parametrize(
    "holes,slots,mask",
    [(False, False, 0), (True, False, 1), (False, True, 4), (True, True, 5)],
)
def test_center_mark_types_and_explicit_size(holes, slots, mask):
    view = NS(AutoInsertCenterMarks2=Mock(return_value=True))
    assert d.auto_center_marks(
        Adapter(), view, holes=holes, slots=slots, size=0.004
    ) is bool(mask)
    if not mask:
        view.AutoInsertCenterMarks2.assert_not_called()
        return
    view.AutoInsertCenterMarks2.assert_called_once_with(
        mask, 0, False, False, False, 0.004, 0.001, True, True, 0.0
    )


@pytest.mark.parametrize(
    "state", ["normal", "no_note", "no_annotation", "position_rejected"]
)
def test_free_note_preserves_exact_text_and_reports_failed_native_creation(
    state, caplog
):
    annotation = NS(SetPosition=Mock(return_value=state != "position_rejected"))
    note = NS(
        GetAnnotation=Mock(
            return_value=None if state == "no_annotation" else annotation
        )
    )
    doc = model(InsertNote=Mock(return_value=None if state == "no_note" else note))
    result = d.add_note(Adapter(doc), '$PRPSHEET:"Title"', 0.1, 0.2)
    doc.InsertNote.assert_called_once_with('$PRPSHEET:"Title"')
    assert result is (None if state == "no_note" else note)
    if state in {"normal", "position_rejected"}:
        annotation.SetPosition.assert_called_once_with(0.1, 0.2, 0.0)
    if state != "normal":
        assert caplog.records


@pytest.mark.parametrize(
    "kind,limits",
    [(d.TOL_BASIC, (0, 0)), (d.TOL_LIMIT, (-0.01, 0.02)), (d.TOL_FIT, (0, 0.02))],
)
def test_tolerance_changes_target_exact_parameter(kind, limits):
    annotation, _, parameter = dimension()
    assert d.set_annotation_tolerance(
        Adapter(), annotation, kind, min_val=limits[0], max_val=limits[1]
    )
    parameter.SetToleranceType.assert_called_once_with(kind)
    if kind == d.TOL_BASIC:
        parameter.SetToleranceValues.assert_not_called()
        return
    parameter.SetToleranceValues.assert_called_once_with(*limits)


def test_border_geometry_and_title_rows_preserve_order(monkeypatch):
    sketch = NS(CreateLine=Mock())
    notes = Mock()
    monkeypatch.setattr(d, "add_note", notes)
    doc = model(SketchManager=sketch)
    assert d.draw_border_and_title_block(
        Adapter(doc),
        ["Title", "Revision"],
        width=0.4,
        height=0.3,
        margin=0.01,
        block_w=0.1,
        row_h=0.02,
    )
    assert sketch.CreateLine.call_count == 9
    assert sketch.CreateLine.call_args_list[0] == call(0.01, 0.01, 0.0, 0.39, 0.01, 0.0)
    assert [row.args[1] for row in notes.call_args_list] == ["Title", "Revision"]
    assert notes.call_args_list[0].args[3] > notes.call_args_list[1].args[3]


def test_table_deletion_includes_sheet_and_view_but_only_selected_annotations():
    yes = NS(Select2=Mock(return_value=True))
    no = NS(Select2=Mock(return_value=False))
    view = NS(
        GetNextView=None, GetTableAnnotations=lambda: (NS(GetAnnotation=lambda: no),)
    )
    sheet = NS(
        GetNextView=view,
        GetTableAnnotations=lambda: (None, NS(GetAnnotation=lambda: yes)),
    )
    doc = model(GetFirstView=lambda: sheet, EditDelete=Mock())
    assert d.delete_all_tables(Adapter(doc)) == 1
    yes.Select2.assert_called_once_with(False, 0)
    no.Select2.assert_called_once_with(False, 0)
    doc.EditDelete.assert_called_once_with()


def test_note_removal_collects_matches_before_mutating_annotation_list():
    events = []

    def annotation(text, next_annotation=None):
        return NS(
            GetSpecificAnnotation=lambda: NS(GetText=lambda: text),
            GetNext3=lambda: next_annotation,
            Select2=lambda *_: events.append(text) or True,
        )

    second = annotation("keep")
    first = annotation("Tapped Hole", second)
    view = NS(GetNextView=None, GetFirstAnnotation3=lambda: first)
    sheet = NS(GetNextView=view)
    doc = model(GetFirstView=lambda: sheet, EditDelete=Mock())
    assert d.remove_notes_matching(Adapter(doc), "tapped") == 1
    assert events == ["Tapped Hole"]


@pytest.mark.parametrize("state", ["created", "missing"])
def test_template_save_requires_new_file_after_stale_removal(tmp_path, state):
    path = tmp_path / "derived.drwdot"
    path.write_bytes(b"stale")

    def save(actual, version, options):
        assert (actual, version, options) == (str(path), 0, 0)
        assert not path.exists()
        if state == "created":
            path.write_bytes(b"new")

    doc = model(SaveAs3=Mock(side_effect=save))
    if state == "missing":
        with pytest.raises(RuntimeError, match="produced no file"):
            d.save_as_template(Adapter(doc), str(path))
        return
    assert d.save_as_template(Adapter(doc), str(path)) == str(path)
    assert path.read_bytes() == b"new"
