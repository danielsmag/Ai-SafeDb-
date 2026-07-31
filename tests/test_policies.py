import hashlib
import json
import textwrap
from pathlib import Path

import pytest
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt
from pydantic import ValidationError

from app.exceptions import ConfigError, PolicyViolationError
from app.middleware import PiiMaskingMiddleware, SqlPolicyMiddleware
from app.policies import PolicyLoader, SqlPolicy


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
                        "pii": [
                            {"column": "email", "action": "mask"},
                            {"column": "ssn", "action": "block"},
                            {"column": "ip_address", "action": "hash"},
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


async def test_pii_masking_middleware_masks_json_and_structured_results() -> None:
    middleware: PiiMaskingMiddleware = PiiMaskingMiddleware(build_policy())
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(name="query", arguments={})
    )
    payload: list[dict[str, str]] = [
        {
            "email": "jane@example.com",
            "ip_address": "192.0.2.1",
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
    expected_hash: str = hashlib.sha256(b"192.0.2.1").hexdigest()[:16]

    assert masked_text[0]["email"] == "j***@example.com"
    assert masked_text[0]["ip_address"] == f"sha256:{expected_hash}"
    assert masked_text[0]["city"] == "Testville"
    assert result.structured_content == {"rows": masked_text}
