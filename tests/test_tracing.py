import logging

import pytest

from app.core.logging import NO_TRACE_ID, logger
from app.core.tracing import current_trace_id, span, trace


def _trace_id_of(record: logging.LogRecord) -> str:
    """The `_TraceIdFilter`-injected trace id, not part of `LogRecord`'s spec."""
    return record.trace_id  # type: ignore[attr-defined]


def test_no_trace_id_outside_a_trace() -> None:
    assert current_trace_id() == NO_TRACE_ID


def test_trace_generates_and_restores_trace_id() -> None:
    assert current_trace_id() == NO_TRACE_ID
    with trace("unit_of_work") as trace_id:
        assert current_trace_id() == trace_id
        assert trace_id != NO_TRACE_ID
    assert current_trace_id() == NO_TRACE_ID


def test_nested_span_reuses_the_enclosing_trace_id() -> None:
    with trace("tool_call") as trace_id:
        with span("guard.review_call"):
            assert current_trace_id() == trace_id
        assert current_trace_id() == trace_id


def test_span_failure_still_propagates_and_restores_state() -> None:
    with trace("tool_call") as trace_id:
        with pytest.raises(ValueError, match="boom"), span("tool.execute"):
            raise ValueError("boom")
        assert current_trace_id() == trace_id


def test_log_records_are_stamped_with_the_active_trace_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    with trace("tool_call") as trace_id:
        logger.info("plain log line inside a trace")

    records: list[logging.LogRecord] = [
        record
        for record in caplog.records
        if record.name == logger.name and "plain log line" in record.getMessage()
    ]
    assert len(records) == 1
    assert _trace_id_of(records[0]) == trace_id


def test_log_records_outside_a_trace_use_the_placeholder(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=logger.name)
    logger.info("plain log line outside any trace")

    records: list[logging.LogRecord] = [
        record
        for record in caplog.records
        if record.name == logger.name and "outside any trace" in record.getMessage()
    ]
    assert len(records) == 1
    assert _trace_id_of(records[0]) == NO_TRACE_ID
