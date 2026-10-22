"""Drawing artifact writes and observation contexts must agree on success."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from solidworks_mcp.adapters.solidworks import drawing
from solidworks_mcp.adapters.solidworks.drawing import save_drawing


@pytest.fixture(autouse=True)
def native_boundary(monkeypatch):
    monkeypatch.setattr(
        drawing._sw_type_info, "early_bound", lambda obj, interface: obj
    )


def _observer(events):
    @contextmanager
    def observe(kind, path):
        events.append(("enter", kind, path))
        try:
            yield
        except Exception as error:
            events.append(("error", kind, error))
            raise
        events.append(("success", kind))

    return observe


@pytest.mark.parametrize("observation", ["enabled", "disabled"])
def test_each_requested_artifact_is_saved_once(tmp_path, monkeypatch, observation):
    monkeypatch.chdir(tmp_path)
    paths = {
        "drawing": "drawing/part.SLDDRW",
        "pdf": "pdf/part.pdf",
        "png": "png/part.png",
    }
    expected = {kind: str(tmp_path / path) for kind, path in paths.items()}
    events = []

    def write(path, version, options, export_data, advanced_options, errors, warnings):
        assert (version, options, export_data, advanced_options, errors, warnings) == (
            0, 1, None, None, 0, 0
        )
        events.append(("save", path))
        Path(path).write_bytes(b"new drawing artifact")
        return True, 0, 0

    extension = SimpleNamespace(SaveAs3=Mock(side_effect=write))
    model = SimpleNamespace(
        Extension=extension,
        SaveAs3=Mock(side_effect=AssertionError("legacy model save must not run")),
    )
    result = save_drawing(
        SimpleNamespace(currentModel=model),
        paths["drawing"],
        pdf_path=paths["pdf"],
        png_path=paths["png"],
        artifact_context=_observer(events) if observation == "enabled" else None,
    )

    assert result == expected
    assert extension.SaveAs3.call_count == 3
    model.SaveAs3.assert_not_called()
    assert all(
        Path(path).read_bytes() == b"new drawing artifact" for path in result.values()
    )
    expected_events = []
    for kind, path in expected.items():
        if observation == "enabled":
            expected_events.append(("enter", kind, path))
        expected_events.append(("save", path))
        if observation == "enabled":
            expected_events.append(("success", kind))
    assert events == expected_events


def test_unrequested_exports_have_no_context_or_save(tmp_path):
    path = tmp_path / "part.SLDDRW"

    def write(output, *_):
        Path(output).write_bytes(b"drawing")
        return True, 0, 0

    save = Mock(side_effect=write)
    events = []

    assert save_drawing(
        SimpleNamespace(
            currentModel=SimpleNamespace(Extension=SimpleNamespace(SaveAs3=save))
        ),
        str(path),
        artifact_context=_observer(events),
    ) == {"drawing": str(path)}
    save.assert_called_once_with(str(path), 0, 1, None, None, 0, 0)
    assert events == [("enter", "drawing", str(path)), ("success", "drawing")]


@pytest.mark.parametrize("failed_kind", ["drawing", "pdf", "png"])
@pytest.mark.parametrize("failure", ["no_output", "exception", "false", "errors"])
def test_failed_write_is_observed_and_stops_later_exports(
    tmp_path, failed_kind, failure
):
    paths = {
        "drawing": tmp_path / "part.SLDDRW",
        "pdf": tmp_path / "part.pdf",
        "png": tmp_path / "part.png",
    }
    for path in paths.values():
        path.write_bytes(b"stale artifact")
    events = []
    com_error = RuntimeError("COM save failed")

    def write(path, *_):
        assert not Path(path).exists(), "the old artifact must be removed before saving"
        if path != str(paths[failed_kind]):
            Path(path).write_bytes(b"new artifact")
            return True, 0, 0
        if failure == "exception":
            raise com_error
        if failure == "false":
            return False, 0, 0
        if failure == "errors":
            Path(path).write_bytes(b"failed artifact")
            return True, 2, 0
        return True, 0, 0

    save = Mock(side_effect=write)
    with pytest.raises(RuntimeError) as raised:
        save_drawing(
            SimpleNamespace(
                currentModel=SimpleNamespace(Extension=SimpleNamespace(SaveAs3=save))
            ),
            str(paths["drawing"]),
            pdf_path=str(paths["pdf"]),
            png_path=str(paths["png"]),
            artifact_context=_observer(events),
        )

    if failure == "exception":
        assert raised.value is com_error
    elif failure == "no_output":
        assert "SaveAs3 produced no file" in str(raised.value)
    else:
        assert "SaveAs3 failed" in str(raised.value)
    assert events[-1] == ("error", failed_kind, raised.value)
    assert paths[failed_kind].exists() == (failure == "errors")
    attempted = list(paths)[: list(paths).index(failed_kind) + 1]
    assert [call.args[0] for call in save.call_args_list] == [
        str(paths[kind]) for kind in attempted
    ]


def test_locked_stale_target_fails_before_com_save(tmp_path, monkeypatch):
    path = tmp_path / "part.SLDDRW"
    path.write_bytes(b"stale artifact")
    removal_error = PermissionError("drawing is locked")
    monkeypatch.setattr(
        "solidworks_mcp.adapters.solidworks.drawing.os.remove",
        Mock(side_effect=removal_error),
    )
    save = Mock()
    events = []

    with pytest.raises(PermissionError) as raised:
        save_drawing(
            SimpleNamespace(
                currentModel=SimpleNamespace(Extension=SimpleNamespace(SaveAs3=save))
            ),
            str(path),
            artifact_context=_observer(events),
        )

    assert raised.value is removal_error
    save.assert_not_called()
    assert path.read_bytes() == b"stale artifact"
    assert events == [
        ("enter", "drawing", str(path)),
        ("error", "drawing", removal_error),
    ]


def test_bound_extension_save_avoids_legacy_source_write(tmp_path, monkeypatch):
    source = tmp_path / "source.SLDPRT"
    source.write_bytes(b"original source")
    output = tmp_path / "part.SLDDRW"

    def legacy_save(*_):
        source.write_bytes(b"unexpected source write")
        raise AssertionError("legacy save must not run")

    def write(path, *_):
        Path(path).write_bytes(b"drawing")
        return True, 0, 0

    legacy = Mock(side_effect=legacy_save)
    raw_extension = SimpleNamespace(SaveAs3=legacy)
    bound_extension = SimpleNamespace(SaveAs3=Mock(side_effect=write))

    def bind(obj, interface):
        assert obj is raw_extension
        assert interface == "IModelDocExtension"
        return bound_extension

    monkeypatch.setattr(drawing._sw_type_info, "early_bound", bind)
    model = SimpleNamespace(Extension=raw_extension, SaveAs3=legacy)

    assert save_drawing(SimpleNamespace(currentModel=model), str(output)) == {
        "drawing": str(output)
    }
    bound_extension.SaveAs3.assert_called_once_with(
        str(output), 0, 1, None, None, 0, 0
    )
    legacy.assert_not_called()
    assert source.read_bytes() == b"original source"


@pytest.mark.parametrize(
    "status",
    [
        pytest.param((False, 0, 0), id="false"),
        pytest.param((True, 2, 0), id="native-error"),
        pytest.param(True, id="scalar"),
        pytest.param((True, 0), id="short-tuple"),
        pytest.param((True, 0, 0, 0), id="long-tuple"),
        pytest.param([True, 0, 0], id="list"),
        pytest.param((1, 0, 0), id="integer-success"),
        pytest.param((None, 0, 0), id="missing-success"),
        pytest.param((True, False, 0), id="bool-errors"),
        pytest.param((True, 0, False), id="bool-warnings"),
        pytest.param((True, 0.0, 0), id="float-errors"),
        pytest.param((True, 0, 0.0), id="float-warnings"),
        pytest.param((True, "0", 0), id="string-errors"),
        pytest.param((True, 0, "0"), id="string-warnings"),
    ],
)
def test_invalid_native_status_rejects_even_with_fresh_file(tmp_path, status):
    path = tmp_path / "part.SLDDRW"
    events = []

    def write(output, *_):
        Path(output).write_bytes(b"fresh but unsuccessful artifact")
        return status

    save = Mock(side_effect=write)
    legacy = Mock(side_effect=AssertionError("legacy save must not run"))
    model = SimpleNamespace(Extension=SimpleNamespace(SaveAs3=save), SaveAs3=legacy)
    with pytest.raises(RuntimeError) as raised:
        save_drawing(
            SimpleNamespace(currentModel=model),
            str(path),
            pdf_path=str(tmp_path / "part.pdf"),
            artifact_context=_observer(events),
        )

    assert "SaveAs3" in str(raised.value)
    assert path.read_bytes() == b"fresh but unsuccessful artifact"
    save.assert_called_once_with(str(path), 0, 1, None, None, 0, 0)
    legacy.assert_not_called()
    assert events == [
        ("enter", "drawing", str(path)),
        ("error", "drawing", raised.value),
    ]


def test_native_warnings_are_logged_without_rejecting_fresh_file(tmp_path, caplog):
    path = tmp_path / "part.SLDDRW"

    def write(output, *_):
        Path(output).write_bytes(b"drawing")
        return True, 0, 4

    save = Mock(side_effect=write)
    with caplog.at_level("WARNING", logger=drawing.__name__):
        result = save_drawing(
            SimpleNamespace(
                currentModel=SimpleNamespace(Extension=SimpleNamespace(SaveAs3=save))
            ),
            str(path),
        )

    assert result == {"drawing": str(path)}
    save.assert_called_once_with(str(path), 0, 1, None, None, 0, 0)
    assert any(
        record.name == drawing.__name__
        and "SaveAs3" in record.getMessage()
        and "4" in record.getMessage()
        and str(path) in record.getMessage()
        for record in caplog.records
    )
