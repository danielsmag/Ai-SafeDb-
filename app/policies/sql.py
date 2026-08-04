"""AST-based deterministic enforcement for SQL policies."""

import re
from typing import Final, cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.expressions.core import Expression

from app.policies.models import AccessRules, PiiAction, PiiColumn, SqlPolicy, TableRule

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
        return list(self.extract_sql_arguments(tool_name, arguments).values())

    def extract_sql_arguments(
        self,
        tool_name: str,
        arguments: dict[str, object] | None,
    ) -> dict[str, str]:
        """Return mapping of argument key -> SQL statement string."""
        if not arguments:
            return {}
        statements: dict[str, str] = {
            key: value
            for key, value in arguments.items()
            if key.lower() in _SQL_ARGUMENT_KEYS and isinstance(value, str)
        }
        if statements:
            return statements
        string_items: list[tuple[str, str]] = [
            (key, value)
            for key, value in arguments.items()
            if isinstance(value, str)
        ]
        if "query" in tool_name.lower() and len(string_items) == 1:
            key, value = string_items[0]
            return {key: value}
        return {}

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
            rule.name: set(rule.columns_by_action("block")) for rule in table_rules
        }
        blocked_rules: list[TableRule] = [
            rule for rule in table_rules if blocked_by_rule[rule.name]
        ]

        for select in statement.find_all(exp.Select):
            for projection in select.expressions:
                unaliased: Expression = projection.unalias()
                is_star: bool = self._is_star(unaliased)
                if is_star:
                    self._enforce_star_projection(table_rules)
                    continue
                if not blocked_rules:
                    continue

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

    def _enforce_star_projection(self, table_rules: list[TableRule]) -> None:
        """Reject SELECT * when blocked columns exist or expansion is impossible."""
        for rule in table_rules:
            if rule.columns_by_action("block"):
                raise SqlPolicyViolation("SELECT * may expose blocked PII columns")
            needs_rewrite: bool = bool(
                rule.columns_by_action("drop") or rule.columns_by_action("mask")
            )
            if needs_rewrite and not rule.columns:
                raise SqlPolicyViolation(
                    "SELECT * cannot be expanded: table columns are not declared"
                )

    def result_pii_rules(self) -> dict[str, PiiColumn]:
        rules: dict[str, PiiColumn] = {}
        for table in self._policy.access.tables:
            for pii in table.pii:
                rules[pii.column] = pii
        return rules

    def hashable_pii_columns(self, sql: str) -> dict[str, list[str]]:
        """Return table -> mask-action columns projected by the SQL."""
        return self._projected_pii_columns(sql, "mask")

    def droppable_pii_columns(self, sql: str) -> dict[str, list[str]]:
        """Return table -> drop-action columns projected by the SQL."""
        return self._projected_pii_columns(sql, "drop")

    def _projected_pii_columns(
        self,
        sql: str,
        action: PiiAction,
    ) -> dict[str, list[str]]:
        try:
            statements: list[Expression] = self._parse(sql)
        except ParseError:
            return {}
        result: dict[str, list[str]] = {}
        for statement in statements:
            selected: set[str] | None = self._selected_columns(statement)
            tables: list[exp.Table] = list(statement.find_all(exp.Table))
            for table in tables:
                rule: TableRule | None = self._policy.access.table_rule(
                    table.name,
                    table.db or None,
                    table.catalog or None,
                )
                if rule is None:
                    continue
                columns: list[str] = [
                    column
                    for column in rule.columns_by_action(action)
                    if selected is None or column in selected
                ]
                if not columns:
                    continue
                result[rule.name] = sorted(set(columns))
        return result

    def expand_stars(self, sql: str) -> str | None:
        """Expand SELECT * / t.* using declared table columns.

        Returns None when the SQL has no star projection or declared columns
        are missing for a referenced table that needs expansion.
        """
        try:
            statements: list[Expression] = self._parse(sql)
        except ParseError as err:
            raise SqlPolicyViolation(f"SQL could not be parsed: {err}") from err

        changed: bool = False
        for statement in statements:
            tables: list[exp.Table] = list(statement.find_all(exp.Table))
            alias_rules: dict[str, TableRule] = {}
            for table in tables:
                rule: TableRule | None = self._policy.access.table_rule(
                    table.name,
                    table.db or None,
                    table.catalog or None,
                )
                if rule is None:
                    continue
                alias_rules[table.alias_or_name.lower()] = rule

            for select in statement.find_all(exp.Select):
                new_expressions: list[Expression] = []
                for projection in select.expressions:
                    unaliased: Expression = projection.unalias()
                    if not self._is_star(unaliased):
                        new_expressions.append(projection)
                        continue
                    qualifier: str | None = None
                    if isinstance(unaliased, exp.Column) and unaliased.table:
                        qualifier = unaliased.table.lower()
                    rules: list[TableRule]
                    if qualifier is not None:
                        matched: TableRule | None = alias_rules.get(qualifier)
                        rules = [matched] if matched is not None else []
                    else:
                        rules = list(alias_rules.values())
                    if not rules or any(not rule.columns for rule in rules):
                        return None
                    for rule in rules:
                        prefix: str = qualifier or ""
                        for column_name in rule.columns:
                            column: exp.Column = (
                                exp.column(column_name, table=prefix)
                                if prefix
                                else exp.column(column_name)
                            )
                            new_expressions.append(column)
                    changed = True
                if changed:
                    select.set("expressions", new_expressions)

        if not changed:
            return None
        return "; ".join(
            statement.sql(dialect=self._policy.dialect) for statement in statements
        )

    def drop_columns(self, sql: str, columns: set[str]) -> str:
        """Remove projections whose output name is in ``columns``."""
        if not columns:
            return sql
        try:
            statements: list[Expression] = self._parse(sql)
        except ParseError as err:
            raise SqlPolicyViolation(f"SQL could not be parsed: {err}") from err

        for statement in statements:
            for select in statement.find_all(exp.Select):
                kept: list[Expression] = []
                for projection in select.expressions:
                    if self._is_star(projection.unalias()):
                        kept.append(projection)
                        continue
                    output_name: str | None = self._projection_name(projection)
                    if output_name is not None and output_name in columns:
                        continue
                    kept.append(projection)
                if not kept:
                    raise SqlPolicyViolation(
                        "dropping PII columns left the SELECT with no projections"
                    )
                select.set("expressions", kept)
        return "; ".join(
            statement.sql(dialect=self._policy.dialect) for statement in statements
        )

    def _parse(self, sql: str) -> list[Expression]:
        parsed: list[Expression | None] = cast(
            list[Expression | None],
            sqlglot.parse(sql, read=self._policy.dialect),
        )
        statements: list[Expression] = [
            statement for statement in parsed if statement is not None
        ]
        if not statements:
            raise ParseError("SQL statement is empty")
        return statements

    @staticmethod
    def _selected_columns(statement: Expression) -> set[str] | None:
        """Return projected column names, or None when the SQL selects a star."""
        selected: set[str] = set()
        for select in statement.find_all(exp.Select):
            for projection in select.expressions:
                unaliased: Expression = projection.unalias()
                if SqlPolicyEnforcer._is_star(unaliased):
                    return None
                for column in projection.find_all(exp.Column):
                    selected.add(column.name.lower())
        return selected

    @staticmethod
    def _is_star(expression: Expression) -> bool:
        return isinstance(expression, exp.Star) or (
            isinstance(expression, exp.Column)
            and isinstance(expression.this, exp.Star)
        )

    @staticmethod
    def _projection_name(projection: Expression) -> str | None:
        alias: str | None = projection.alias_or_name
        if alias:
            return alias.lower()
        unaliased: Expression = projection.unalias()
        if isinstance(unaliased, exp.Column):
            return unaliased.name.lower()
        return None
