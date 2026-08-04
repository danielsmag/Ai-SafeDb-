"""Prompts for LLM-driven in-query PII hashing."""

from typing import Final

DATA_KEY_PLACEHOLDER: Final[str] = "__DATA_KEY__"

_HASH_TEMPLATE: Final[str] = (
    "encode(sha256(convert_to('__DATA_KEY__' || <column>::text, 'UTF8')), 'hex')"
    " AS <column>"
)
_EXAMPLE_INPUT: Final[str] = "SELECT id, email FROM customers ORDER BY id LIMIT 3"
_EXAMPLE_OUTPUT: Final[str] = (
    "SELECT id, encode(sha256(convert_to('__DATA_KEY__' || email::text, 'UTF8')),"
    " 'hex') AS email FROM customers ORDER BY id LIMIT 3"
)

PII_HASH_REWRITE_PROMPT: Final[str] = f"""You rewrite one SQL query so that listed
sensitive columns are hashed inside the database.

Hard rules:
1. Keep the projected output list identical: same columns, same order, same
   number of columns, same output names. Never add or drop a column.
2. Only wrap the columns listed as PII in the user message. Leave every other
   column, and the whole FROM/JOIN/WHERE/GROUP/ORDER/LIMIT part, untouched.
3. Wrap each listed PII column with exactly this expression, keeping its
   original output name:
   {_HASH_TEMPLATE}
4. <column> is a bare column reference, never a quoted string. Hashing the
   literal 'email' instead of the column email is wrong.
5. Keep the literal placeholder {DATA_KEY_PLACEHOLDER} verbatim; never invent a
   secret.
6. Write valid PostgreSQL. Do not break identifiers such as sha256 apart.
7. Return only JSON matching the supplied schema, key rewritten_sql.

Example
Input SQL: {_EXAMPLE_INPUT}
PII columns: public.customers: email
Correct rewritten_sql:
{_EXAMPLE_OUTPUT}
"""
