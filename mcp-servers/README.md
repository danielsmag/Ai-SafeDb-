# Server definitions

Every `*.yaml` / `*.yml` file in this folder defines one source MCP server that the
gateway re-exposes at `/mcp/<name>`. Files are loaded at startup; restart the
gateway after changing them.

Fields:

| Field | Required | Description |
| --- | --- | --- |
| `name` | no | URL segment for the exposed endpoint. Defaults to the file name. Lowercase letters, digits, `.`, `_`, `-`. |
| `enabled` | no | `false` keeps the file as a template without mounting it. Defaults to `true`. |
| `description` | no | Passed through as the exposed server's instructions. |
| `source.transport` | yes | `stdio`, `http`, or `sse`. |
| `source.command`, `source.args`, `source.env`, `source.cwd` | stdio only | Child process to launch. |
| `source.url`, `source.headers`, `source.read_timeout_seconds` | http/sse only | Remote MCP server to call. |
| `tools.allow` | no | Empty means all tools. Supports wildcards (`read_*`). |
| `tools.block` | no | Always wins over `allow`. Supports wildcards. |

Any string value may reference the environment as `${VAR}` or `${VAR:-fallback}`,
so tokens stay out of these files. A `${VAR}` without a fallback that is unset
makes startup fail with a clear error.
