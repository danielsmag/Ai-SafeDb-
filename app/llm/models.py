"""Validated messages and responses for OpenAI-compatible chat APIs."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

type ChatRole = Literal["system", "user", "assistant", "tool"]
type Decision = Literal["allow", "block"]


class ChatToolFunction(BaseModel):
    """Function call selected by a chat model."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    name: str
    arguments: str


class ChatToolCall(BaseModel):
    """Tool call emitted by a chat model."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    id: str
    type: Literal["function"] = "function"
    function: ChatToolFunction


class ChatMessage(BaseModel):
    """One portable chat-completion message."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    role: ChatRole
    content: str | None = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ChatToolCall] | None = None


class ChatCompletion(BaseModel):
    """Normalized first choice from a chat-completion response."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    message: ChatMessage
    finish_reason: str | None = None


class GuardVerdict(BaseModel):
    """Validated safety decision returned by a guard model."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    decision: Decision
    reason: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0, le=1)
