"""Central application logger, logging configuration, and correlation ids."""

import contextvars
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Final
from uuid import UUID

_LOG_FORMAT: Final[str] = (
    "%(asctime)s %(levelname)-8s %(name)s "
    "[trace=%(trace_id)s session=%(session_id)s "
    "mcp_session=%(mcp_session_id)s key=%(api_key_name)s]: %(message)s"
)
LOGGER_NAME: Final[str] = "aisafedb"
NO_TRACE_ID: Final[str] = "-"
NO_SESSION: Final[str] = "-"

logger: logging.Logger = logging.getLogger(LOGGER_NAME)

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "trace_id", default=NO_TRACE_ID
)
session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "session_id", default=NO_SESSION
)
mcp_session_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mcp_session_id", default=NO_SESSION
)
api_key_name_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "api_key_name", default=NO_SESSION
)

_base_record_factory: Callable[..., logging.LogRecord] = logging.getLogRecordFactory()


def _correlation_record_factory(*args: object, **kwargs: object) -> logging.LogRecord:
    record: logging.LogRecord = _base_record_factory(*args, **kwargs)
    record.trace_id = trace_id_var.get()
    record.session_id = session_id_var.get()
    record.mcp_session_id = mcp_session_id_var.get()
    record.api_key_name = api_key_name_var.get()
    return record


logging.setLogRecordFactory(_correlation_record_factory)


def configure_logging(level: str | int) -> None:
    """Configure root logging for the application."""
    logging.basicConfig(level=level, format=_LOG_FORMAT)


@contextmanager
def bind_session(
    *,
    session_id: UUID | str,
    mcp_session_id: str,
    api_key_name: str,
) -> Iterator[None]:
    """Attach gateway session identity to log records for this context."""
    session_token: contextvars.Token[str] = session_id_var.set(str(session_id))
    mcp_token: contextvars.Token[str] = mcp_session_id_var.set(mcp_session_id)
    key_token: contextvars.Token[str] = api_key_name_var.set(api_key_name)
    try:
        yield
    finally:
        session_id_var.reset(session_token)
        mcp_session_id_var.reset(mcp_token)
        api_key_name_var.reset(key_token)
