"""Structured tracing for one MCP tool call's journey through the gateway.

`trace()` starts a short-lived trace id when a tool call enters the gateway.
Nested `span()` blocks (a guard review, an LLM HTTP request, ...) run inside
that trace and log their own start/done/failed lines with latency. Log calls
elsewhere in the app (see `app.core.logging`) pick up the ambient trace id
automatically via a logging filter, so a single trace id ties together every
log line produced while handling one tool call without threading it through
every function signature.

No external tracing dependency (e.g. OpenTelemetry) is used; this is a
lightweight, log-based substitute sized for this project.
"""

import contextvars
import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from app.core.logging import logger, trace_id_var


@contextmanager
def trace(name: str, **fields: object) -> Iterator[str]:
    """Start a new trace for one unit of work (e.g. an incoming tool call).

    Establishes the trace id that nested `span()` calls and any other log
    line emitted during the `with` block will be correlated under.
    """
    trace_id: str = uuid.uuid4().hex[:12]
    token: contextvars.Token[str] = trace_id_var.set(trace_id)
    started_at: float = time.perf_counter()
    logger.info("%s start %s", name, _format_fields(fields))
    try:
        yield trace_id
    except Exception as err:
        _log_outcome(name, started_at, err, logging.INFO)
        raise
    else:
        _log_outcome(name, started_at, None, logging.INFO)
    finally:
        trace_id_var.reset(token)


@contextmanager
def span(name: str, **fields: object) -> Iterator[None]:
    """A nested sub-step within the current trace, logged at DEBUG.

    Reuses whatever trace id is currently active; if called outside a
    `trace()` block, log lines carry the "no trace" placeholder id.
    """
    started_at: float = time.perf_counter()
    logger.debug("%s start %s", name, _format_fields(fields))
    try:
        yield
    except Exception as err:
        _log_outcome(name, started_at, err, logging.DEBUG)
        raise
    else:
        _log_outcome(name, started_at, None, logging.DEBUG)


def current_trace_id() -> str:
    """The id of the trace currently being processed, if any."""
    return trace_id_var.get()


def _log_outcome(
    name: str,
    started_at: float,
    error: Exception | None,
    level: int,
) -> None:
    elapsed_ms: float = (time.perf_counter() - started_at) * 1000
    if error is None:
        logger.log(level, "%s done latency_ms=%.1f", name, elapsed_ms)
    else:
        logger.log(
            level,
            "%s failed error=%s latency_ms=%.1f",
            name,
            type(error).__name__,
            elapsed_ms,
        )


def _format_fields(fields: dict[str, object]) -> str:
    return " ".join(f"{key}={value!r}" for key, value in fields.items())
