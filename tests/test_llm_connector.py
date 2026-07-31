import json

import httpx
import pytest

from app.exceptions import LlmUnavailableError
from app.llm import ChatMessage, OpenAICompatibleLlmClient


async def test_openai_client_sends_schema_to_v1_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": '{"ok":true}'},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    http_client = httpx.AsyncClient(
        base_url="http://llm.test/v1",
        transport=httpx.MockTransport(handler),
    )
    client = OpenAICompatibleLlmClient(
        base_url="http://unused.test/v1",
        api_key="test",
        timeout_seconds=1,
        max_concurrency=1,
        keep_alive="10m",
        client=http_client,
    )

    completion = await client.complete(
        [ChatMessage(role="user", content="classify")],
        model="guard",
        schema={"type": "object"},
    )

    assert completion.message.content == '{"ok":true}'
    assert str(requests[0].url) == "http://llm.test/v1/chat/completions"
    payload = json.loads(requests[0].content)
    assert payload["response_format"]["type"] == "json_schema"
    await http_client.aclose()


async def test_openai_client_rejects_invalid_response() -> None:
    http_client = httpx.AsyncClient(
        base_url="http://llm.test/v1",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"choices": []})
        ),
    )
    client = OpenAICompatibleLlmClient(
        base_url="http://unused.test/v1",
        api_key="test",
        timeout_seconds=1,
        max_concurrency=1,
        keep_alive="10m",
        client=http_client,
    )

    with pytest.raises(LlmUnavailableError, match="invalid"):
        await client.complete(
            [ChatMessage(role="user", content="classify")],
            model="guard",
        )
    await http_client.aclose()
