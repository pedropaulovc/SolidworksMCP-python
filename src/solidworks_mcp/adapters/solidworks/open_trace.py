"""Name every document open in the caller's trace and log.

``OpenDoc6`` is the COM call most likely to sit for a long time: it resolves
references, rebuilds, and can wait behind a modal nobody will click. A host
that watches its own telemetry for silence (harmonic-analyzer's COM watchdog)
can only say WHICH open wedged if the open has a span of its own. Without an
OpenTelemetry SDK installed the API's tracer is a no-op, so a standalone
server pays nothing for this.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from loguru import logger
from opentelemetry import trace

_tracer = trace.get_tracer("solidworks_mcp")


@contextmanager
def opening(operation: str, path: str, doc_type: int) -> Iterator[None]:
    """Log ``opening <file>`` and hold a ``<operation> <file>`` span around the open.

    Args:
        operation: Span name prefix, e.g. ``sw.open`` or ``sw.preload``.
        path: Absolute path of the document being opened.
        doc_type: The ``swDocumentTypes_e`` value passed to ``OpenDoc6``.
    """
    name = os.path.basename(path)
    logger.info(f"opening {name}")
    with _tracer.start_as_current_span(
        f"{operation} {name}", attributes={"path": path, "doc_type": doc_type}
    ):
        yield
