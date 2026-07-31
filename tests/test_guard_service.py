import json

import pytest

from app.llm import ChatCompletion, ChatMessage
from app.core.config import GuardErrorMode
from app.exceptions import LlmUnavailableError
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
