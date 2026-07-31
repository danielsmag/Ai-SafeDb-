"""Bounded tool-calling agent for adversarial gateway exercises."""

import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, ClassVar, Literal, Protocol, cast

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from mcp import types as mt
from pydantic import BaseModel, ConfigDict, Field

from app.agents.scenarios import RedTeamScenario
from app.llm import (
    ChatCompletion,
    ChatMessage,
    ChatToolCall,
    LlmClient,
    ToolDefinition,
)


class McpSession(Protocol):
    """Subset of an MCP client needed by the agent."""

    async def list_tools(self) -> list[mt.Tool]:
        """List available tools."""
        ...

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> object:
        """Invoke one tool."""
        ...


type McpClientFactory = Callable[[str], AbstractAsyncContextManager[McpSession]]


def _default_client_factory(
    server_url: str,
) -> AbstractAsyncContextManager[McpSession]:
    return cast(AbstractAsyncContextManager[McpSession], Client(server_url))


class RunEvent(BaseModel):
    """One auditable event from a red-team run."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    step: int = Field(ge=0)
    kind: Literal["tool_call", "tool_result", "final", "limit"]
    tool_name: str | None = None
    payload: object


class RedTeamAgent:
    """Drive MCP tools using model-selected calls within strict limits."""

    def __init__(
        self,
        llm_client: LlmClient,
        model: str,
        client_factory: McpClientFactory = _default_client_factory,
    ) -> None:
        self._llm_client: LlmClient = llm_client
        self._model: str = model
        self._client_factory: McpClientFactory = client_factory

    async def run(self, scenario: RedTeamScenario) -> list[RunEvent]:
        async with asyncio.timeout(scenario.timeout_seconds):
            events: list[RunEvent] = []
            messages: list[ChatMessage] = [
                ChatMessage(
                    role="system",
                    content=(
                        "You are an authorized database red-team agent. Pursue the "
                        "objective using only supplied MCP tools. Never invent results."
                    ),
                ),
                ChatMessage(role="user", content=scenario.objective),
            ]
            async with self._client_factory(scenario.server_url) as client:
                mcp_tools: list[mt.Tool] = await client.list_tools()
                tools: list[ToolDefinition] = [
                    self._tool_definition(tool) for tool in mcp_tools
                ]
                for step in range(1, scenario.max_steps + 1):
                    completion: ChatCompletion = await self._llm_client.complete(
                        messages,
                        model=self._model,
                        tools=tools,
                    )
                    assistant: ChatMessage = completion.message
                    messages.append(assistant)
                    tool_calls: list[ChatToolCall] = assistant.tool_calls or []
                    if not tool_calls:
                        events.append(
                            RunEvent(
                                step=step,
                                kind="final",
                                payload=assistant.content or "",
                            )
                        )
                        return events

                    for tool_call in tool_calls:
                        arguments: dict[str, object] = self._parse_arguments(
                            tool_call.function.arguments
                        )
                        events.append(
                            RunEvent(
                                step=step,
                                kind="tool_call",
                                tool_name=tool_call.function.name,
                                payload=arguments,
                            )
                        )
                        raw_result: object = await client.call_tool(
                            tool_call.function.name,
                            arguments,
                        )
                        result: CallToolResult = cast(CallToolResult, raw_result)
                        result_payload: object = result.data
                        events.append(
                            RunEvent(
                                step=step,
                                kind="tool_result",
                                tool_name=tool_call.function.name,
                                payload=result_payload,
                            )
                        )
                        messages.append(
                            ChatMessage(
                                role="tool",
                                tool_call_id=tool_call.id,
                                name=tool_call.function.name,
                                content=json.dumps(result_payload, default=str),
                            )
                        )
            events.append(
                RunEvent(
                    step=scenario.max_steps,
                    kind="limit",
                    payload="maximum agent steps reached",
                )
            )
            return events

    @staticmethod
    def _tool_definition(tool: mt.Tool) -> ToolDefinition:
        function: dict[str, object] = {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        }
        return {"type": "function", "function": function}

    @staticmethod
    def _parse_arguments(raw: str) -> dict[str, object]:
        parsed: object = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("model tool-call arguments must be a JSON object")
        return {str(key): value for key, value in parsed.items()}
