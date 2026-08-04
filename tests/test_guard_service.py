import json
import logging

import pytest

from app.core.config import GuardErrorMode
from app.exceptions import LlmUnavailableError
from app.llm import ChatCompletion, ChatMessage
from app.services.guard import GuardService
from tests.fakes import FakeLlmClient


def completion(decision: str = "allow") -> ChatCompletion:
    return ChatCompletion(
        message=ChatMessage(
            role="assistant",
            content=json.dumps(
                {
                    "decision": decision,
                    "reason": "scripted verdict",
                    "confidence": 0.9,
                }
            ),
        )
    )


async def test_guard_uses_structured_model_verdict_and_cache() -> None:
    client = FakeLlmClient([completion()])
    guard = GuardService(client, "guard", "block", cache_ttl_seconds=60)

    first = await guard.review_call("source", "read", {"query": "SELECT 1 LIMIT 1"})
    second = await guard.review_call("source", "read", {"query": "SELECT 1 LIMIT 1"})

    assert first.decision == second.decision == "allow"
    assert len(client.calls) == 1
    assert client.reasoning_efforts == ["none"]


async def test_guard_logs_full_question_and_answer_at_debug(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client: FakeLlmClient = FakeLlmClient([completion()])
    guard: GuardService = GuardService(
        client,
        "guard",
        "block",
        cache_ttl_seconds=60,
    )
    caplog.set_level(logging.DEBUG, logger="aisafedb")

    await guard.review_call("source", "read", {"query": "SELECT 1 LIMIT 1"})

    log_text: str = caplog.text
    assert "Guard LLM question kind=call model=guard" in log_text
    assert "SYSTEM:" in log_text
    assert "USER:" in log_text
    assert "SELECT 1 LIMIT 1" in log_text
    assert "Guard LLM answer kind=call model=guard" in log_text
    assert "scripted verdict" in log_text


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("block", "block"), ("allow", "allow")],
)
async def test_guard_applies_configured_error_mode(
    mode: GuardErrorMode,
    expected: GuardErrorMode,
) -> None:
    client = FakeLlmClient(error=LlmUnavailableError("offline"))
    guard = GuardService(client, "guard", mode, cache_ttl_seconds=0)

    verdict = await guard.review_call(
        "source",
        "read",
        {"query": "SELECT 1 LIMIT 1"},
    )

    assert verdict.decision == expected


async def test_guard_blocks_malformed_model_json_when_fail_closed() -> None:
    client = FakeLlmClient(
        [ChatCompletion(message=ChatMessage(role="assistant", content="not-json"))]
    )
    guard = GuardService(client, "guard", "block", cache_ttl_seconds=0)

    verdict = await guard.review_call(
        "source",
        "read",
        {"query": "SELECT 1 LIMIT 1"},
    )

    assert verdict.decision == "block"


async def test_guard_accepts_percentage_confidence_from_model() -> None:
    client = FakeLlmClient(
        [
            ChatCompletion(
                message=ChatMessage(
                    role="assistant",
                    content=json.dumps(
                        {
                            "decision": "allow",
                            "reason": "narrow read",
                            "confidence": 100,
                        }
                    ),
                )
            )
        ]
    )
    guard = GuardService(client, "guard", "block", cache_ttl_seconds=0)

    verdict = await guard.review_call("source", "read", {"query": "SELECT 1 LIMIT 1"})

    assert verdict.decision == "allow"
    assert verdict.confidence == 1.0


async def test_guard_allows_protected_result_without_calling_model() -> None:
    client: FakeLlmClient = FakeLlmClient([])
    guard: GuardService = GuardService(client, "guard", "block", cache_ttl_seconds=0)

    verdict = await guard.review_result(
        "source",
        "read",
        '[{"id":1,"ip_address":"0d889721"}]',
        None,
        "column ip_address holds keyed SHA-256 digests",
    )

    assert verdict.decision == "allow"
    assert "protected per policy" in verdict.reason
    assert client.calls == []


async def test_guard_blocks_pii_without_calling_model() -> None:
    client = FakeLlmClient([])
    guard = GuardService(client, "guard", "block", cache_ttl_seconds=60)

    verdict = await guard.review_result(
        "source",
        "read",
        "email=customer@example.com",
    )

    assert verdict.decision == "block"
    assert client.calls == []


async def test_guard_blocks_pii_call_args_without_policy() -> None:
    client: FakeLlmClient = FakeLlmClient([])
    guard: GuardService = GuardService(
        client, "guard", "block", cache_ttl_seconds=60
    )

    verdict = await guard.review_call(
        "source",
        "query",
        {"sql": "SELECT email, phone FROM customers LIMIT 3"},
    )

    assert verdict.decision == "block"
    assert "sensitive personal data" in verdict.reason
    assert client.calls == []


async def test_guard_defers_maskable_pii_call_when_policy_present() -> None:
    client: FakeLlmClient = FakeLlmClient([completion("allow")])
    guard: GuardService = GuardService(
        client, "guard", "block", cache_ttl_seconds=60
    )
    policy_context: str = (
        '{"name":"pg-readonly","type":"sql","pii":[{"column":"email","action":"mask"}]}'
    )

    verdict = await guard.review_call(
        "postgres",
        "query",
        {"sql": "SELECT email, phone FROM customers LIMIT 3"},
        policy_context=policy_context,
    )

    assert verdict.decision == "allow"
    assert len(client.calls) == 1
    user_prompt: str = client.calls[0][-1].content or ""
    assert "Policy:" in user_prompt
    assert "email" in user_prompt
