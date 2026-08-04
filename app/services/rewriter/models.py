"""Validated LLM response for in-query PII hashing rewrites."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field


class QueryRewrite(BaseModel):
    """Structured rewrite of a SQL statement with PII columns hashed."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    rewritten_sql: str = Field(min_length=1)
