from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp.client.client import CallToolResult
from mcp import types as mt

from app.agents import RedTeamAgent, RedTeamScenario
from app.llm import ChatCompletion, ChatMessage, ChatToolCall, ChatToolFunction
from tests.fakes import FakeLlmClient


class FakeMcpSession:
    async def list_tools(self) -> list[mt.Tool]:
        return [
            mt.Tool(
                name="query",
                description="Run query",
                inputSchema={"type": "object", "properties": {}},
            )
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> CallToolResult:
        return CallToolResult(
            content=[],
            structured_content=None,
            meta=None,
            data={"count": 1},
        )


@asynccontextmanager
async def fake_client_factory(server_url: str) -> AsyncIterator[FakeMcpSession]:
    yield FakeMcpSession()


def tool_completion() -> ChatCompletion:
    return ChatCompletion(
        message=ChatMessage(
            role="assistant",
            tool_calls=[
                ChatToolCall(
                    id="call-1",
                    function=ChatToolFunction(name="query", arguments="{}"),
                )
            ],
        )
    )


async def test_agent_runs_tool_then_stops_on_final_answer() -> None:
    llm = FakeLlmClient(
        [
            tool_completion(),
            ChatCompletion(
                message=ChatMessage(
                    role="assistant", content="guard blocked extraction"
                )
            ),
        ]
    )
    agent = RedTeamAgent(llm, "agent", client_factory=fake_client_factory)
    scenario = RedTeamScenario(name="test", objective="test", max_steps=2)

    events = await agent.run(scenario)

    assert [event.kind for event in events] == [
        "tool_call",
        "tool_result",
        "final",
    ]


async def test_agent_records_step_limit() -> None:
    llm = FakeLlmClient([tool_completion()])
    agent = RedTeamAgent(llm, "agent", client_factory=fake_client_factory)
    scenario = RedTeamScenario(name="test", objective="test", max_steps=1)

    events = await agent.run(scenario)

    assert events[-1].kind == "limit"
