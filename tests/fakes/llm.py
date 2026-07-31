"""Scripted local-model fake for unit tests."""

from collections import deque

from app.llm import (
    ChatCompletion,
    ChatMessage,
    JsonSchema,
    ReasoningEffort,
    ToolDefinition,
)


class FakeLlmClient:
    def __init__(
        self,
        completions: list[ChatCompletion] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.completions: deque[ChatCompletion] = deque(completions or [])
        self.error: Exception | None = error
        self.calls: list[list[ChatMessage]] = []
        self.reasoning_efforts: list[ReasoningEffort | None] = []
        self.closed: bool = False

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        schema: JsonSchema | None = None,
        tools: list[ToolDefinition] | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> ChatCompletion:
        self.calls.append(messages)
        self.reasoning_efforts.append(reasoning_effort)
        if self.error is not None:
            raise self.error
        return self.completions.popleft()

    async def close(self) -> None:
        self.closed = True
