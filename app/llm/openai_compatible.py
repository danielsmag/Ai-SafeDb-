"""Asynchronous adapter for OpenAI-compatible local model servers."""

import asyncio
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from app.llm.models import ChatCompletion, ChatMessage
from app.llm.protocols import JsonSchema, ToolDefinition
from app.exceptions import LlmUnavailableError


class _Choice(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    message: ChatMessage
    finish_reason: str | None = None


class _CompletionResponse(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore")

    choices: list[_Choice]


class OpenAICompatibleLlmClient:
    """Small OpenAI-compatible client with bounded local-model concurrency."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        max_concurrency: int,
        keep_alive: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._keep_alive: str = keep_alive
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrency)
        self._owns_client: bool = client is None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        schema: JsonSchema | None = None,
        tools: list[ToolDefinition] | None = None,
    ) -> ChatCompletion:
        payload: dict[str, object] = {
            "model": model,
            "messages": [message.model_dump(exclude_none=True) for message in messages],
            "stream": False,
            "keep_alive": self._keep_alive,
        }
        if schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": schema},
            }
        if tools is not None:
            payload["tools"] = tools

        async with self._semaphore:
            response: httpx.Response = await self._post_with_retry(payload)

        try:
            parsed: _CompletionResponse = _CompletionResponse.model_validate(
                response.json()
            )
            choice: _Choice = parsed.choices[0]
        except (ValueError, ValidationError, IndexError) as err:
            raise LlmUnavailableError("invalid chat-completion response") from err
        return ChatCompletion(
            message=choice.message,
            finish_reason=choice.finish_reason,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _post_with_retry(self, payload: dict[str, object]) -> httpx.Response:
        for attempt in range(2):
            try:
                response: httpx.Response = await self._client.post(
                    "/chat/completions",
                    json=payload,
                )
                response.raise_for_status()
                return response
            except (httpx.ConnectError, httpx.ConnectTimeout) as err:
                if attempt == 1:
                    raise LlmUnavailableError("local LLM is unreachable") from err
                await asyncio.sleep(0)
            except httpx.TimeoutException as err:
                raise LlmUnavailableError("local LLM request timed out") from err
            except httpx.HTTPStatusError as err:
                detail: str = self._safe_error_detail(err.response)
                raise LlmUnavailableError(
                    f"local LLM returned HTTP {err.response.status_code}: {detail}"
                ) from err
        raise AssertionError("retry loop exhausted")

    @staticmethod
    def _safe_error_detail(response: httpx.Response) -> str:
        try:
            body: Any = response.json()
        except ValueError:
            return response.text[:200]
        if isinstance(body, dict):
            error: object = body.get("error")
            if isinstance(error, dict):
                message: object = error.get("message")
                if isinstance(message, str):
                    return message[:200]
            if isinstance(error, str):
                return error[:200]
        return "request failed"
