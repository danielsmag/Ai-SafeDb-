"""LLM-assisted rewrite of SQL to hash PII columns in-query."""

from typing import Final, cast

import sqlglot
from pydantic import ValidationError
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.expressions.core import Expression

from app.core.config import GuardErrorMode
from app.core.logging import logger
from app.core.tracing import span
from app.exceptions import LlmUnavailableError
from app.llm import ChatCompletion, ChatMessage, LlmClient
from app.policies.models import SqlDialect
from app.services.rewriter.models import QueryRewrite
from app.services.rewriter.prompts import DATA_KEY_PLACEHOLDER, PII_HASH_REWRITE_PROMPT

_REWRITE_SCHEMA: Final[dict[str, object]] = QueryRewrite.model_json_schema()
_MAX_ATTEMPTS: Final[int] = 2


class RewriteRejected(ValueError):
    """The model returned SQL that does not satisfy the rewrite contract."""


class PiiQueryRewriter:
    """Ask a local model to wrap policy PII columns in keyed SHA-256 expressions."""

    def __init__(
        self,
        client: LlmClient,
        model: str,
        on_error: GuardErrorMode,
    ) -> None:
        self._client: LlmClient = client
        self._model: str = model
        self._on_error: GuardErrorMode = on_error

    async def rewrite(
        self,
        sql: str,
        dialect: SqlDialect,
        pii_columns: dict[str, list[str]],
    ) -> str | None:
        """Return rewritten SQL still containing ``__DATA_KEY__``, or None to skip.

        Returns None when there are no PII columns, or when the model fails and
        ``on_error`` is ``allow``. Raises ``LlmUnavailableError`` when the model
        fails and ``on_error`` is ``block``. A rejected rewrite is retried once
        with the validation error fed back to the model.
        """
        if not pii_columns:
            return None

        subject: str = self._build_subject(sql, dialect, pii_columns)
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=PII_HASH_REWRITE_PROMPT),
            ChatMessage(role="user", content=subject),
        ]
        logger.debug(
            "PII rewrite LLM question model=%s\nSYSTEM:\n%s\nUSER:\n%s",
            self._model,
            PII_HASH_REWRITE_PROMPT,
            subject,
        )
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            content: str | None = None
            try:
                content = await self._complete(messages)
                rewrite: QueryRewrite = QueryRewrite.model_validate_json(content)
                rewritten_sql: str = rewrite.rewritten_sql.strip()
                self._validate(sql, rewritten_sql, dialect, pii_columns)
                return rewritten_sql
            except LlmUnavailableError as err:
                return self._handle_failure(err)
            except (ValidationError, RewriteRejected, ValueError, ParseError) as err:
                last_error = err
                logger.warning(
                    "PII rewrite attempt %d/%d rejected: %s",
                    attempt,
                    _MAX_ATTEMPTS,
                    err,
                )
                if attempt == _MAX_ATTEMPTS:
                    break
                messages = [
                    *messages[:2],
                    ChatMessage(role="assistant", content=content or ""),
                    ChatMessage(
                        role="user",
                        content=(
                            f"That answer was rejected: {err}\n"
                            "Return corrected JSON that obeys every rule."
                        ),
                    ),
                ]
        assert last_error is not None
        return self._handle_failure(last_error)

    async def _complete(self, messages: list[ChatMessage]) -> str:
        with span("llm.rewrite_pii", model=self._model):
            completion: ChatCompletion = await self._client.complete(
                messages,
                model=self._model,
                schema=_REWRITE_SCHEMA,
                reasoning_effort="none",
            )
        content: str | None = completion.message.content
        if content is None:
            raise LlmUnavailableError("rewrite model returned no content")
        logger.debug(
            "PII rewrite LLM answer model=%s\n%s",
            self._model,
            content,
        )
        return content

    def _handle_failure(self, err: Exception) -> None:
        logger.warning(
            "PII query rewrite failed (%s): %s",
            type(err).__name__,
            err,
        )
        if self._on_error == "allow":
            return
        raise LlmUnavailableError(f"PII query rewrite unavailable: {err}") from err

    @staticmethod
    def _build_subject(
        sql: str,
        dialect: SqlDialect,
        pii_columns: dict[str, list[str]],
    ) -> str:
        columns_lines: list[str] = []
        for table, columns in sorted(pii_columns.items()):
            joined: str = ", ".join(sorted(columns))
            columns_lines.append(f"- {table}: {joined}")
        columns_block: str = "\n".join(columns_lines)
        return (
            f"Dialect: {dialect}\n"
            f"Data-key placeholder: {DATA_KEY_PLACEHOLDER}\n"
            f"PII columns to hash (table: columns):\n{columns_block}\n"
            f"Original SQL:\n{sql}"
        )

    def _validate(
        self,
        original_sql: str,
        rewritten_sql: str,
        dialect: SqlDialect,
        pii_columns: dict[str, list[str]],
    ) -> None:
        rewritten: list[Expression] = self._parse(rewritten_sql, dialect)
        if DATA_KEY_PLACEHOLDER not in rewritten_sql:
            raise RewriteRejected(
                f"rewritten SQL must contain the {DATA_KEY_PLACEHOLDER} placeholder"
            )

        targets: set[str] = {
            column for columns in pii_columns.values() for column in columns
        }
        referenced: set[str] = {
            column.name.lower()
            for statement in rewritten
            for column in statement.find_all(exp.Column)
        }
        missing: set[str] = targets - referenced
        if missing:
            raise RewriteRejected(
                "hashed columns must be bare column references, missing: "
                + ", ".join(sorted(missing))
            )

        original: list[Expression] = self._parse(original_sql, dialect)
        expected_names: list[str] = self._output_names(original)
        actual_names: list[str] = self._output_names(rewritten)
        if "*" in expected_names:
            return
        if expected_names != actual_names:
            raise RewriteRejected(
                f"output columns changed: expected {expected_names}, "
                f"got {actual_names}"
            )

    @staticmethod
    def _parse(sql: str, dialect: SqlDialect) -> list[Expression]:
        parsed: list[Expression | None] = cast(
            list[Expression | None],
            sqlglot.parse(sql, read=dialect),
        )
        statements: list[Expression] = [
            statement for statement in parsed if statement is not None
        ]
        if not statements:
            raise RewriteRejected("SQL is empty")
        return statements

    @staticmethod
    def _output_names(statements: list[Expression]) -> list[str]:
        names: list[str] = []
        for statement in statements:
            select: exp.Select | None = (
                statement if isinstance(statement, exp.Select) else None
            )
            if select is None:
                select = statement.find(exp.Select)
            if select is None:
                continue
            names.extend(name.lower() for name in select.named_selects)
        return names
