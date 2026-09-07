"""Drawing artifact writes and observation contexts must agree on success."""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from solidworks_mcp.adapters.solidworks.drawing import save_drawing


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

    def write(path, version, options):
        assert (version, options) == (0, 0)
        events.append(("save", path))
        Path(path).write_bytes(b"new drawing artifact")
        return 0

    model = SimpleNamespace(SaveAs3=Mock(side_effect=write))
    result = save_drawing(
        SimpleNamespace(currentModel=model),
        paths["drawing"],
        pdf_path=paths["pdf"],
        png_path=paths["png"],
        artifact_context=_observer(events) if observation == "enabled" else None,
    )

    assert result == expected
    assert model.SaveAs3.call_count == 3
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
    save = Mock(side_effect=lambda output, *_: Path(output).write_bytes(b"drawing"))
    events = []

    assert save_drawing(
        SimpleNamespace(currentModel=SimpleNamespace(SaveAs3=save)),
        str(path),
        artifact_context=_observer(events),
    ) == {"drawing": str(path)}
    save.assert_called_once_with(str(path), 0, 0)
    assert events == [("enter", "drawing", str(path)), ("success", "drawing")]


@pytest.mark.parametrize("failed_kind", ["drawing", "pdf", "png"])
@pytest.mark.parametrize("failure", ["no_output", "exception"])
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
            return 0
        if failure == "exception":
            raise com_error
        return 1

    save = Mock(side_effect=write)
    with pytest.raises(RuntimeError) as raised:
        save_drawing(
            SimpleNamespace(currentModel=SimpleNamespace(SaveAs3=save)),
            str(paths["drawing"]),
            pdf_path=str(paths["pdf"]),
            png_path=str(paths["png"]),
            artifact_context=_observer(events),
        )

    if failure == "exception":
        assert raised.value is com_error
    else:
        assert "SaveAs3 produced no file" in str(raised.value)
    assert events[-1] == ("error", failed_kind, raised.value)
    assert not paths[failed_kind].exists()
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
            SimpleNamespace(currentModel=SimpleNamespace(SaveAs3=save)),
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
