"""Validated models for YAML policy definitions."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

type PiiAction = Literal["block", "drop", "mask", "allow"]
# Backward-compatible alias; prefer PiiAction.
type MaskAction = PiiAction
type SqlDialect = Literal[
    "bigquery",
    "clickhouse",
    "databricks",
    "duckdb",
    "mysql",
    "oracle",
    "postgres",
    "redshift",
    "snowflake",
    "spark",
    "sqlite",
    "sqlserver",
    "trino",
]


class PiiColumn(BaseModel):
    """Sensitivity rule for one result column."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    column: str = Field(min_length=1)
    action: PiiAction = "mask"
    kind: str | None = Field(default=None, min_length=1)

    @field_validator("column")
    @classmethod
    def normalize_column(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("action", mode="before")
    @classmethod
    def alias_hash_to_mask(cls, value: object) -> object:
        """Accept legacy ``hash`` as an alias of ``mask``."""
        if isinstance(value, str) and value.strip().lower() == "hash":
            return "mask"
        return value


class TableRule(BaseModel):
    """Access and sensitivity rules for one SQL table."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    columns: list[str] = Field(default_factory=list)
    pii: list[PiiColumn] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("columns")
    @classmethod
    def normalize_columns(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values]

    def pii_rule(self, column: str) -> PiiColumn | None:
        normalized: str = column.lower()
        return next((rule for rule in self.pii if rule.column == normalized), None)

    def columns_by_action(self, action: PiiAction) -> list[str]:
        return [pii.column for pii in self.pii if pii.action == action]


class AccessRules(BaseModel):
    """Allow lists for SQL database objects; empty lists allow all."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    databases: list[str] = Field(default_factory=list)
    schemas: list[str] = Field(default_factory=list)
    tables: list[TableRule] = Field(default_factory=list)

    @field_validator("databases", "schemas")
    @classmethod
    def normalize_names(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values]

    def table_rule(
        self,
        table: str,
        schema: str | None = None,
        database: str | None = None,
    ) -> TableRule | None:
        candidates: list[str] = [table.lower()]
        if schema:
            candidates.insert(0, f"{schema.lower()}.{table.lower()}")
        if database and schema:
            candidates.insert(
                0,
                f"{database.lower()}.{schema.lower()}.{table.lower()}",
            )
        exact: TableRule | None = next(
            (rule for rule in self.tables if rule.name in candidates),
            None,
        )
        if exact is not None or schema is not None:
            return exact
        return next(
            (
                rule
                for rule in self.tables
                if rule.name.rsplit(".", maxsplit=1)[-1] == table.lower()
            ),
            None,
        )


class SqlPolicy(BaseModel):
    """Deterministic SQL access and data-masking policy."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=64)
    type: Literal["sql"]
    dialect: SqlDialect = "postgres"
    read_only: bool = True
    denied_keywords: list[str] = Field(default_factory=list)
    access: AccessRules = Field(default_factory=AccessRules)

    @field_validator("denied_keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values]


type Policy = SqlPolicy
