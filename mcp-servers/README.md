# Server definitions

Every `*.yaml` / `*.yml` file in this folder defines one source MCP server that the
gateway re-exposes at `/mcp/<name>`. Files are loaded at startup; restart the
gateway after changing them.

Clients must send `Authorization: Bearer <api_key>` on every MCP HTTP request.
The local-dev seed key is `aisk_dev_local_00000000000000000001` (hashed in
`{SAFE_DB_SCHEMA}.api_keys`). Sessions are stored in `{SAFE_DB_SCHEMA}.sessions`.

Fields:

| Field | Required | Description |
| --- | --- | --- |
| `name` | no | URL segment for the exposed endpoint. Defaults to the file name. Lowercase letters, digits, `.`, `_`, `-`. |
| `enabled` | no | `false` keeps the file as a template without mounting it. Defaults to `true`. |
| `description` | no | Passed through as the exposed server's instructions. |
| `policy` | no | Name of a validated YAML policy from `policies/`. Unknown names fail startup. |
| `source.transport` | yes | `stdio`, `http`, or `sse`. |
| `source.command`, `source.args`, `source.env`, `source.cwd` | stdio only | Child process to launch. |
| `source.url`, `source.headers`, `source.read_timeout_seconds` | http/sse only | Remote MCP server to call. |
| `tools.allow` | no | Empty means all tools. Supports wildcards (`read_*`). |
| `tools.block` | no | Always wins over `allow`. Supports wildcards. |
| `guard.enabled` | no | Overrides global local-LLM guard enablement for this server. |
| `guard.inspect_results` | no | Overrides global result inspection for this server. |

Any string value may reference the environment as `${VAR}` or `${VAR:-fallback}`,
so tokens stay out of these files. A `${VAR}` without a fallback that is unset
makes startup fail with a clear error.

## SQL policies

SQL policies live in `policies/*.yaml`. Each file declares `type: sql`, a
`sqlglot` dialect, read-only behavior, denied keywords, database/schema/table
allow lists, and optional PII handling per table column. Empty allow lists mean
all values at that level are allowed.

Each table may declare a `columns` list (full column set). The gateway uses it
to expand `SELECT *` / `t.*` before applying per-column PII rules.

PII actions are:

- `block`: reject a query that selects the column (and reject `SELECT *`).
- `drop`: remove the column from the query projection; the call still runs.
- `mask` (default): keyed-hash the column in-query with the session `data_key`.
- `allow`: return the column unchanged.
- `hash`: legacy alias of `mask` (still accepted in YAML).

When a SQL policy is attached and a session is recognized, the gateway expands
stars, drops `drop` columns deterministically, then asks a local LLM (see
`GATEWAY_LLM__REWRITE_MODEL`) to wrap remaining `mask` columns with keyed
SHA-256 **inside the SQL** before the query reaches the source server. The
model only ever sees the placeholder `__DATA_KEY__`; the gateway substitutes
the real key after the rewritten statement is re-validated by the same SQL
policy. On rewrite failure, behavior follows `GATEWAY_GUARD__ON_ERROR`
(`block` rejects; `allow` forwards the prepared query and falls back to
result-side masking / dropping). Successful in-query hashing skips result
masking for `mask` columns on that call so hashes are not mangled; `drop`
columns are still stripped from results if they somehow appear.

Policy files reference `policies/policy.schema.json` for editor validation.
After changing policy models, regenerate it with `make policy-schema`.
