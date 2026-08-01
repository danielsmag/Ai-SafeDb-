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

PII actions are:

- `block`: reject a query selecting the column (and reject `SELECT *`).
- `mask`: redact matching result fields while retaining useful shape.
- `hash`: replace matching result fields with a deterministic SHA-256 prefix.

Policy files reference `policies/policy.schema.json` for editor validation.
After changing policy models, regenerate it with `make policy-schema`.
