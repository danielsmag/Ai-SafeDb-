"""Per-call record of what the gateway did to a tool call and its result."""

from typing import Any, ClassVar, Final

from fastmcp.server.middleware import MiddlewareContext
from pydantic import BaseModel, ConfigDict, Field

from app.llm import Decision

REPORT_STATE_KEY: Final[str] = "aisafedb_report"
REPORT_META_KEY: Final[str] = "aisafedb"


class ToolCallReport(BaseModel):
    """Audit trail for one guarded tool call.

    ``executed_sql`` holds the statement actually sent downstream with the
    session ``data_key`` replaced by its placeholder, so the report never
    carries the secret.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    server: str
    tool: str
    executed_sql: list[str] = Field(default_factory=list)
    expanded_stars: bool = False
    dropped_columns: list[str] = Field(default_factory=list)
    hashed_columns: list[str] = Field(default_factory=list)
    masked_fields: list[str] = Field(default_factory=list)
    removed_fields: list[str] = Field(default_factory=list)
    call_decision: Decision | None = None
    result_decision: Decision | None = None

    def summary(self) -> str:
        """One human-readable line describing the applied protections."""
        parts: list[str] = []
        if self.expanded_stars:
            parts.append("expanded SELECT *")
        if self.dropped_columns:
            parts.append(f"dropped columns {', '.join(self.dropped_columns)}")
        if self.hashed_columns:
            parts.append(f"hashed in query {', '.join(self.hashed_columns)}")
        if self.masked_fields:
            parts.append(f"masked in result {', '.join(self.masked_fields)}")
        if self.removed_fields:
            parts.append(f"removed from result {', '.join(self.removed_fields)}")
        if not parts:
            parts.append("no PII transforms applied")
        if self.call_decision is not None:
            parts.append(f"guard call={self.call_decision}")
        if self.result_decision is not None:
            parts.append(f"guard result={self.result_decision}")
        return f"aisafedb: {'; '.join(parts)}"


async def start_report(
    context: MiddlewareContext[Any],
    server_name: str,
    tool_name: str,
) -> ToolCallReport | None:
    """Create the request-scoped report other middleware then fill in."""
    fastmcp_context = context.fastmcp_context
    if fastmcp_context is None:
        return None
    report: ToolCallReport = ToolCallReport(server=server_name, tool=tool_name)
    await fastmcp_context.set_state(REPORT_STATE_KEY, report, serializable=False)
    return report


async def get_report(context: MiddlewareContext[Any]) -> ToolCallReport | None:
    """Return the report for the current call, when one is being collected."""
    fastmcp_context = context.fastmcp_context
    if fastmcp_context is None:
        return None
    report: object = await fastmcp_context.get_state(REPORT_STATE_KEY)
    return report if isinstance(report, ToolCallReport) else None
