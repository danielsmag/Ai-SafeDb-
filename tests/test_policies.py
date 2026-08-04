import json
import textwrap
from pathlib import Path
from uuid import uuid4

import pytest
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt
from pydantic import ValidationError

from app.connectors.models import ClientInfo
from app.exceptions import ConfigError, PolicyViolationError
from app.llm import ChatCompletion, ChatMessage
from app.middleware import (
    PII_HASHED_IN_QUERY_STATE_KEY,
    PiiHashRewriteMiddleware,
    PiiMaskingMiddleware,
    SqlPolicyMiddleware,
)
from app.policies import PolicyLoader, SqlPolicy
from app.policies.sql import SqlPolicyEnforcer
from app.services.rewriter import DATA_KEY_PLACEHOLDER, PiiQueryRewriter, QueryRewrite
from app.services.session import MemorySessionService
from tests.fakes import FakeFastMcpContext, FakeLlmClient


def _completion(content: str) -> ChatCompletion:
    return ChatCompletion(message=ChatMessage(role="assistant", content=content))


def build_policy() -> SqlPolicy:
    return SqlPolicy.model_validate(
        {
            "name": "test-policy",
            "type": "sql",
            "dialect": "postgres",
            "read_only": True,
            "denied_keywords": ["pg_sleep"],
            "access": {
                "databases": ["appdb"],
                "schemas": ["public"],
                "tables": [
                    {
                        "name": "public.customers",
                        "columns": [
                            "id",
                            "email",
                            "ssn",
                            "ip_address",
                            "credit_card",
                            "city",
                        ],
                        "pii": [
                            {"column": "email", "action": "mask"},
                            {"column": "ssn", "action": "block"},
                            {"column": "ip_address", "action": "hash"},
                            {"column": "credit_card", "action": "drop"},
                            {"column": "city", "action": "allow"},
                        ],
                    }
                ],
            },
        }
    )


def test_policy_model_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SqlPolicy.model_validate(
            {
                "name": "invalid",
                "type": "sql",
                "not_a_rule": True,
            }
        )


def test_hash_action_aliases_to_mask() -> None:
    policy: SqlPolicy = build_policy()
    rule = policy.access.table_rule("customers", "public")
    assert rule is not None
    ip = rule.pii_rule("ip_address")
    assert ip is not None
    assert ip.action == "mask"


def test_policy_loader_reads_yaml_and_defaults_name(tmp_path: Path) -> None:
    policies_dir: Path = tmp_path / "policies"
    policies_dir.mkdir()
    (policies_dir / "readonly.yaml").write_text(
        textwrap.dedent(
            """
            type: sql
            dialect: postgres
            read_only: true
            """
        ).lstrip(),
        encoding="utf-8",
    )

    policies: dict[str, SqlPolicy] = PolicyLoader(policies_dir, environ={}).load()

    assert policies["readonly"].read_only is True


def test_policy_loader_rejects_invalid_yaml(tmp_path: Path) -> None:
    policies_dir: Path = tmp_path / "policies"
    policies_dir.mkdir()
    (policies_dir / "bad.yaml").write_text("type: unknown\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        PolicyLoader(policies_dir, environ={}).load()


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("DELETE FROM customers", "read-only"),
        ("SELECT pg_sleep(1)", "denied keyword"),
        ("SELECT id FROM private.customers", "schema"),
        ("SELECT id FROM public.orders", "table"),
        ("SELECT ssn FROM customers", "blocked as PII"),
        ("SELECT * FROM customers", "SELECT *"),
    ],
)
async def test_sql_policy_middleware_blocks_violations(
    sql: str,
    reason: str,
) -> None:
    middleware: SqlPolicyMiddleware = SqlPolicyMiddleware(
        build_policy(),
        server_name="postgres",
    )
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(name="query", arguments={"sql": sql})
    )

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(content=[mt.TextContent(type="text", text="ok")])

    with pytest.raises(PolicyViolationError, match=reason):
        await middleware.on_call_tool(context, call_next)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, email FROM customers LIMIT 10",
        "SELECT COUNT(*) FROM customers",
        "SELECT COUNT(*) FROM customers WHERE ssn = '000-00-0000'",
    ],
)
async def test_sql_policy_middleware_allows_narrow_read(sql: str) -> None:
    middleware: SqlPolicyMiddleware = SqlPolicyMiddleware(
        build_policy(),
        server_name="postgres",
    )
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={"sql": sql},
        )
    )

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(content=[mt.TextContent(type="text", text="ok")])

    result: ToolResult = await middleware.on_call_tool(context, call_next)
    text: mt.ContentBlock = result.content[0]

    assert isinstance(text, mt.TextContent)
    assert text.text == "ok"


def test_expand_stars_uses_declared_columns() -> None:
    enforcer: SqlPolicyEnforcer = SqlPolicyEnforcer(build_policy())
    expanded: str | None = enforcer.expand_stars("SELECT * FROM public.customers")
    assert expanded is not None
    assert "email" in expanded.lower()
    assert "ssn" in expanded.lower()
    assert "*" not in expanded.replace("customers", "")


def test_drop_columns_removes_projections() -> None:
    enforcer: SqlPolicyEnforcer = SqlPolicyEnforcer(build_policy())
    dropped: str = enforcer.drop_columns(
        "SELECT id, credit_card, email FROM public.customers",
        {"credit_card"},
    )
    assert "credit_card" not in dropped.lower()
    assert "email" in dropped.lower()


async def test_middleware_drops_column_without_llm() -> None:
    store: MemorySessionService = MemorySessionService()
    api_key = await store.authenticate("aisk_dev_local_00000000000000000001")
    assert api_key is not None
    mcp_session_id: str = f"mcp-{uuid4()}"
    await store.open_session(
        mcp_session_id=mcp_session_id,
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(),
    )
    middleware: PiiHashRewriteMiddleware = PiiHashRewriteMiddleware(
        PiiQueryRewriter(
            FakeLlmClient([_completion("{}")]),
            model="test",
            on_error="block",
        ),
        build_policy(),
        store,
        server_name="postgres",
        on_error="block",
    )
    captured_sql: list[str] = []
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={"sql": "SELECT id, credit_card FROM public.customers"},
        ),
        fastmcp_context=FakeFastMcpContext(mcp_session_id),  # type: ignore[arg-type]
    )

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        args = context.message.arguments
        assert args is not None
        captured_sql.append(str(args["sql"]))
        return ToolResult(content=[mt.TextContent(type="text", text="ok")])

    await middleware.on_call_tool(context, call_next)
    assert len(captured_sql) == 1
    assert "credit_card" not in captured_sql[0].lower()
    assert "id" in captured_sql[0].lower()


async def test_middleware_expand_drop_then_mask() -> None:
    store: MemorySessionService = MemorySessionService()
    api_key = await store.authenticate("aisk_dev_local_00000000000000000001")
    assert api_key is not None
    mcp_session_id: str = f"mcp-{uuid4()}"
    session = await store.open_session(
        mcp_session_id=mcp_session_id,
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(),
    )
    # After expand + drop of credit_card/ssn-blocked star rejection is separate;
    # use an explicit select that needs drop then mask.
    rewrite: QueryRewrite = QueryRewrite(
        rewritten_sql=(
            "SELECT id, encode(sha256(convert_to("
            f"'{DATA_KEY_PLACEHOLDER}' || email::text, 'UTF8')), 'hex') AS email "
            "FROM public.customers"
        )
    )
    middleware: PiiHashRewriteMiddleware = PiiHashRewriteMiddleware(
        PiiQueryRewriter(
            FakeLlmClient([_completion(rewrite.model_dump_json())]),
            model="test",
            on_error="block",
        ),
        build_policy(),
        store,
        server_name="postgres",
        on_error="block",
    )
    captured_sql: list[str] = []
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={
                "sql": "SELECT id, credit_card, email FROM public.customers",
            },
        ),
        fastmcp_context=FakeFastMcpContext(mcp_session_id),  # type: ignore[arg-type]
    )

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        args = context.message.arguments
        assert args is not None
        captured_sql.append(str(args["sql"]))
        return ToolResult(content=[mt.TextContent(type="text", text="ok")])

    await middleware.on_call_tool(context, call_next)
    assert len(captured_sql) == 1
    assert "credit_card" not in captured_sql[0].lower()
    assert DATA_KEY_PLACEHOLDER not in captured_sql[0]
    assert session.data_key in captured_sql[0]
    assert "email" in captured_sql[0].lower()


async def test_pii_masking_middleware_masks_and_drops_results() -> None:
    middleware: PiiMaskingMiddleware = PiiMaskingMiddleware(build_policy())
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(name="query", arguments={})
    )
    payload: list[dict[str, str]] = [
        {
            "email": "jane@example.com",
            "ip_address": "192.0.2.1",
            "credit_card": "4111",
            "city": "Testville",
        }
    ]

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(
            content=[
                mt.TextContent(type="text", text=json.dumps(payload)),
            ],
            structured_content={"rows": payload},
        )

    result: ToolResult = await middleware.on_call_tool(context, call_next)
    text: mt.ContentBlock = result.content[0]
    assert isinstance(text, mt.TextContent)
    masked_text: list[dict[str, str]] = json.loads(text.text)

    assert masked_text[0]["email"] == "j***@example.com"
    assert masked_text[0]["ip_address"] == "1***1"
    assert "credit_card" not in masked_text[0]
    assert masked_text[0]["city"] == "Testville"
    assert result.structured_content == {"rows": masked_text}


async def test_pii_masking_skips_mask_when_hashed_but_still_drops() -> None:
    middleware: PiiMaskingMiddleware = PiiMaskingMiddleware(build_policy())
    fake_ctx: FakeFastMcpContext = FakeFastMcpContext("mcp-sess")
    await fake_ctx.set_state(PII_HASHED_IN_QUERY_STATE_KEY, True)
    payload: list[dict[str, str]] = [
        {
            "email": "already-hashed",
            "credit_card": "4111",
            "city": "Testville",
        }
    ]
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(name="query", arguments={}),
        fastmcp_context=fake_ctx,  # type: ignore[arg-type]
    )

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(
            content=[mt.TextContent(type="text", text=json.dumps(payload))],
            structured_content={"rows": payload},
        )

    result: ToolResult = await middleware.on_call_tool(context, call_next)
    rows = result.structured_content
    assert rows is not None
    assert rows["rows"][0]["email"] == "already-hashed"
    assert "credit_card" not in rows["rows"][0]
    assert rows["rows"][0]["city"] == "Testville"
