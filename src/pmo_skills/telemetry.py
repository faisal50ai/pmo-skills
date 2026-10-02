"""Opt-in local OpenTelemetry JSON spans; never capture project text or source quotes."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import Span

_provider: TracerProvider | None = None
_stream: IO[str] | None = None


def configure(path: Path) -> None:
    """Export one JSON span per line, exclusively to the requested new file."""
    global _provider, _stream
    if _provider is not None:
        raise RuntimeError("Tracing is already configured")
    _stream = path.open("x", encoding="utf-8")
    _provider = TracerProvider(sampler=ALWAYS_ON, resource=Resource({"service.name": "pmo-skills"}))
    _provider.add_span_processor(
        SimpleSpanProcessor(
            ConsoleSpanExporter(
                out=_stream, formatter=lambda span: span.to_json(indent=None) + "\n"
            )
        )
    )


@contextmanager
def operation(name: str) -> Iterator[Span]:
    tracer = _provider.get_tracer("pmo_skills") if _provider else trace.get_tracer("pmo_skills")
    # Disable automatic exception events: validation errors can contain source text.
    with tracer.start_as_current_span(
        name, record_exception=False, set_status_on_exception=False
    ) as s:
        try:
            yield s
        except Exception:
            s.set_status(trace.Status(trace.StatusCode.ERROR))
            raise


def close() -> None:
    global _provider, _stream
    if _provider:
        _provider.shutdown()
    if _stream:
        _stream.close()
    _provider, _stream = None, None
