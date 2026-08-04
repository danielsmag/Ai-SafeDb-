import pytest

from app.services.guard import PiiPrefilter, SqlRiskPrefilter


@pytest.mark.parametrize(
    "text",
    [
        "select * from customers",
        "DELETE FROM customers WHERE id = 1",
        '{"query":"drop table customers"}',
    ],
)
def test_sql_prefilter_blocks_risky_queries(text: str) -> None:
    verdict = SqlRiskPrefilter().inspect(text)

    assert verdict is not None
    assert verdict.decision == "block"


def test_sql_prefilter_defers_bounded_read() -> None:
    assert SqlRiskPrefilter().inspect("SELECT id FROM customers LIMIT 5") is None


@pytest.mark.parametrize(
    "text",
    [
        "SSN: 123-45-6789",
        "customer@example.com",
        "4111 1111 1111 1111",
    ],
)
def test_pii_prefilter_blocks_sensitive_results(text: str) -> None:
    verdict = PiiPrefilter().inspect_result(text)

    assert verdict is not None
    assert verdict.decision == "block"


def test_pii_prefilter_ignores_benign_result() -> None:
    assert PiiPrefilter().inspect_result('{"count": 3}') is None


def test_pii_prefilter_blocks_sensitive_call_args() -> None:
    verdict = PiiPrefilter().inspect_call(
        '{"sql":"SELECT email, phone FROM customers LIMIT 3"}'
    )

    assert verdict is not None
    assert verdict.decision == "block"
    assert "sensitive personal data" in verdict.reason
