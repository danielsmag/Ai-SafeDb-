# Define a server

One YAML file per source server under `mcp-servers/`. Full field reference:
`mcp-servers/README.md` in the repository.

## Stdio example

```yaml
name: github
enabled: true
source:
  transport: stdio
  command: npx
  args: ["-y", "@modelcontextprotocol/server-github"]
  env:
    GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_TOKEN}
tools:
  allow: []            # empty = all tools
  block: [delete_*]
```

## Common fields

| Field | Required | Description |
| --- | --- | --- |
| `name` | no | URL segment; defaults to file name |
| `enabled` | no | `false` keeps file as template |
| `source.transport` | yes | `stdio`, `http`, or `sse` |
| `tools.allow` / `tools.block` | no | Wildcards; block wins |
| `policy` | no | Name of YAML in `policies/` |
| `guard.*` | no | Per-server guard overrides |

Any string may use `${VAR}` or `${VAR:-fallback}`. Unset required vars fail
startup.

## SQL policies

Live in `policies/*.yaml` (`type: sql`). Support dialect, denied keywords,
DB/schema/table allow lists, and per-column PII actions: `block`, `drop`,
`mask`, `allow` (`hash` = legacy `mask`).
