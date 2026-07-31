"""Central application logger, logging configuration, and trace correlation."""

import contextvars
import logging
from collections.abc import Callable
from typing import Final

_LOG_FORMAT: Final[str] = (
    "%(asctime)s %(levelname)-8s %(name)s [trace=%(trace_id)s]: %(message)s"
)
LOGGER_NAME: Final[str] = "aisafedb"
NO_TRACE_ID: Final[str] = "-"

logger: logging.Logger = logging.getLogger(LOGGER_NAME)

# Holds the id of the trace currently being processed (see app.core.tracing).
# Living here, next to the logger, lets the record factory below tag every
# log record without every call site having to pass a trace id around
# explicitly.
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=NO_TRACE_ID
)

# A per-logger Filter would only stamp records from that one logger: records
# from other loggers (uvicorn, mcp, starlette, fastmcp, ...) reach the root
# handler without passing through it, leaving `trace_id` unset and breaking
# `_LOG_FORMAT`. A global record factory stamps every record from every
# logger at creation time instead.
_base_record_factory: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()


def _trace_id_record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
    record: logging.LogRecord = _base_record_factory(*args, **kwargs)
    record.trace_id = trace_id_var.get()
    return record


logging.setLogRecordFactory(_trace_id_record_factory)


def configure_logging(level: str | int) -> None:
    """Configure root logging for the application."""
    logging.basicConfig(level=level, format=_LOG_FORMAT)
