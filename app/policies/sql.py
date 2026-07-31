"""AST-based deterministic enforcement for SQL policies."""

import re
from typing import Final, cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.expressions.core import Expression

from app.policies.models import AccessRules, PiiColumn, SqlPolicy, TableRule

_SQL_ARGUMENT_KEYS: Final[frozenset[str]] = frozenset(
    {"query", "sql", "statement", "sql_query"}
)
_MUTATING_NODES: Final[tuple[type[Expression], ...]] = (
    exp.Alter,
    exp.Command,
    exp.Copy,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Merge,
    exp.TruncateTable,
    exp.Update,
)


class SqlPolicyViolation(ValueError):
    """A SQL statement violates a configured deterministic rule."""


class SqlPolicyEnforcer:
    """Parse SQL and enforce one immutable policy."""

    def __init__(self, policy: SqlPolicy) -> None:
        self._policy: SqlPolicy = policy

    def extract_sql(
        self,
        tool_name: str,
        arguments: dict[str, object] | None,
    ) -> list[str]:
        if not arguments:
            return []
        statements: list[str] = [
            value
            for key, value in arguments.items()
            if key.lower() in _SQL_ARGUMENT_KEYS and isinstance(value, str)
        ]
        if statements:
            return statements
        string_values: list[str] = [
            value for value in arguments.values() if isinstance(value, str)
        ]
        if "query" in tool_name.lower() and len(string_values) == 1:
            return string_values
        return []

    def enforce(self, sql: str) -> None:
        try:
            parsed: list[Expression | None] = cast(
                list[Expression | None],
                sqlglot.parse(
                    sql,
                    read=self._policy.dialect,
                ),
            )
        except ParseError as err:
            raise SqlPolicyViolation(f"SQL could not be parsed: {err}") from err
        statements: list[Expression] = [
            statement for statement in parsed if statement is not None
        ]
        if not statements:
            raise SqlPolicyViolation("SQL statement is empty")

        for statement in statements:
            self._enforce_statement(statement, sql)

    def _enforce_statement(self, statement: Expression, raw_sql: str) -> None:
        if self._policy.read_only:
            if not isinstance(statement, exp.Query):
                raise SqlPolicyViolation("policy permits read-only SQL only")
            if any(statement.find(node) is not None for node in _MUTATING_NODES):
                raise SqlPolicyViolation("query contains a data-changing operation")
        self._enforce_denied_keywords(raw_sql)
        tables: list[exp.Table] = list(statement.find_all(exp.Table))
        self._enforce_table_access(tables)
        self._enforce_blocked_pii(statement, tables)

    def _enforce_denied_keywords(self, raw_sql: str) -> None:
        for keyword in self._policy.denied_keywords:
            pattern: re.Pattern[str] = re.compile(
                rf"(?<![A-Za-z0-9_]){re.escape(keyword)}(?![A-Za-z0-9_])",
                re.IGNORECASE,
            )
            if pattern.search(raw_sql):
                raise SqlPolicyViolation(f"query contains denied keyword {keyword!r}")

    def _enforce_table_access(self, tables: list[exp.Table]) -> None:
        access: AccessRules = self._policy.access
        for table in tables:
            database: str | None = table.catalog or None
            schema: str | None = table.db or None
            name: str = table.name
            if (
                access.databases
                and database
                and database.lower() not in access.databases
            ):
                raise SqlPolicyViolation(f"database {database!r} is not allowed")
            if access.schemas and schema and schema.lower() not in access.schemas:
                raise SqlPolicyViolation(f"schema {schema!r} is not allowed")
            if access.tables and access.table_rule(name, schema, database) is None:
                qualified: str = ".".join(
                    part for part in (database, schema, name) if part
                )
                raise SqlPolicyViolation(f"table {qualified!r} is not allowed")

    def _enforce_blocked_pii(
        self,
        statement: Expression,
        tables: list[exp.Table],
    ) -> None:
        table_rules: list[TableRule] = []
        alias_rules: dict[str, TableRule] = {}
        for table in tables:
            rule: TableRule | None = self._policy.access.table_rule(
                table.name,
                table.db or None,
                table.catalog or None,
            )
            if rule is None:
                continue
            table_rules.append(rule)
            alias: str = table.alias_or_name.lower()
            alias_rules[alias] = rule

        blocked_by_rule: dict[str, set[str]] = {
            rule.name: {pii.column for pii in rule.pii if pii.action == "block"}
            for rule in table_rules
        }
        blocked_rules: list[TableRule] = [
            rule for rule in table_rules if blocked_by_rule[rule.name]
        ]
        if not blocked_rules:
            return

        for select in statement.find_all(exp.Select):
            for projection in select.expressions:
                unaliased: Expression = projection.unalias()
                is_star: bool = isinstance(unaliased, exp.Star) or (
                    isinstance(unaliased, exp.Column)
                    and isinstance(unaliased.this, exp.Star)
                )
                if is_star:
                    raise SqlPolicyViolation("SELECT * may expose blocked PII columns")

                for column in projection.find_all(exp.Column):
                    column_name: str = column.name.lower()
                    qualifier: str = column.table.lower()
                    if qualifier:
                        rule = alias_rules.get(qualifier)
                        if rule and column_name in blocked_by_rule[rule.name]:
                            raise SqlPolicyViolation(
                                f"column {column.sql()!r} is blocked as PII"
                            )
                        continue
                    if any(
                        column_name in blocked_by_rule[rule.name]
                        for rule in blocked_rules
                    ):
                        raise SqlPolicyViolation(
                            f"column {column_name!r} is blocked as PII"
                        )

    def result_pii_rules(self) -> dict[str, PiiColumn]:
        rules: dict[str, PiiColumn] = {}
        for table in self._policy.access.tables:
            for pii in table.pii:
                rules[pii.column] = pii
        return rules
