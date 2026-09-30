"""Every OpenDoc6 runs inside a span named for the file it opens."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from loguru import logger
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode

from solidworks_mcp.adapters.base import AdapterResult, AdapterResultStatus
from solidworks_mcp.adapters.solidworks import assembly as assembly_module
from solidworks_mcp.adapters.solidworks import open_trace
from solidworks_mcp.adapters.solidworks.io import SolidWorksIOMixin

PART = r"C:\models\cone-gear.SLDPRT"


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(open_trace, "_tracer", provider.get_tracer("test"))
    return exporter


@pytest.fixture
def messages() -> Any:
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(m.record["message"]), level="INFO")
    yield seen
    logger.remove(sink)


class _IOHarness(SolidWorksIOMixin):
    def __init__(self, app: Any) -> None:
        self.swApp = app
        self.currentModel = None
        self.constants = {"swDocPART": 1, "swDocASSEMBLY": 2, "swDocDRAWING": 3}

    def is_connected(self) -> bool:
        return True

    def _attempt(self, callback, default=None):
        try:
            return callback()
        except Exception:
            return default

    def _handle_com_operation(self, _name, callback, *args):
        try:
            return AdapterResult(status=AdapterResultStatus.SUCCESS, data=callback())
        except Exception as exc:
            return AdapterResult(status=AdapterResultStatus.ERROR, error=str(exc))


@pytest.mark.asyncio
async def test_open_model_runs_opendoc6_inside_a_span_named_for_the_file(
    spans: InMemorySpanExporter, messages: list[str]
) -> None:
    inside: list[str] = []

    def open_doc(*_args: Any) -> Any:
        inside.append(trace.get_current_span().name)
        raise RuntimeError("wedged open")

    result = await _IOHarness(SimpleNamespace(OpenDoc6=open_doc)).open_model(PART)

    assert result.is_error
    assert inside == ["sw.open cone-gear.SLDPRT"]
    (span,) = spans.get_finished_spans()
    assert span.name == "sw.open cone-gear.SLDPRT"
    assert span.attributes["doc_type"] == 1
    assert span.attributes["path"].endswith("cone-gear.SLDPRT")
    assert span.status.status_code is StatusCode.ERROR
    assert messages == ["opening cone-gear.SLDPRT"]


def test_component_preload_runs_opendoc6_inside_a_span_named_for_the_file(
    spans: InMemorySpanExporter, messages: list[str]
) -> None:
    inside: list[str] = []
    model = object()

    def open_doc(*_args: Any) -> Any:
        inside.append(trace.get_current_span().name)
        return (model, 0, 0)

    app = SimpleNamespace(
        OpenDoc6=open_doc,
        DocumentVisible=lambda *_args: None,
        GetOpenDocumentByName=lambda _path: None,
    )
    adapter = SimpleNamespace(
        swApp=app, _attempt=lambda callback, default=None: callback()
    )

    assembly_module._preload_component_file(adapter, PART)

    assert inside == ["sw.preload cone-gear.SLDPRT"]
    (span,) = spans.get_finished_spans()
    assert span.name == "sw.preload cone-gear.SLDPRT"
    assert span.status.status_code is StatusCode.UNSET
    assert messages == ["opening cone-gear.SLDPRT"]
