"""LLM connector contracts."""

from typing import Literal, Protocol

from app.llm.models import ChatCompletion, ChatMessage

type JsonSchema = dict[str, object]
type ToolDefinition = dict[str, object]
type ReasoningEffort = Literal["none", "low", "medium", "high", "max"]


class LlmClient(Protocol):
    """Portable asynchronous chat-completion client."""

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        schema: JsonSchema | None = None,
        tools: list[ToolDefinition] | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> ChatCompletion:
        """Complete a conversation using an optional schema or tool list."""
        ...

    async def close(self) -> None:
        """Release owned network resources."""
        ...
