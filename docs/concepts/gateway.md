# Gateway

The gateway loads YAML definitions at startup, builds a FastMCP proxy per
server, and mounts each at `{GATEWAY_MOUNT_PREFIX}/{name}` (default `/mcp/<name>`).

```text
Client  --Bearer API key-->  Gateway  --policy/guard-->  Source MCP
```

## Boot flow

1. Validate settings (`settings.toml`, then `GATEWAY_*` env / `.env`)
2. Scan `GATEWAY_CONFIG_DIR` for `*.yaml` / `*.yml`
3. Expand `${VAR}` / `${VAR:-fallback}` in definition strings
4. Attach SQL policies from `policies/` when referenced
5. Mount MCP apps and register HTTP routes (health, servers, UI, API)

Invalid definitions or missing required env vars abort startup with the
offending file name.

## Sessions

Successful MCP connects create a row in `{SAFE_DB_SCHEMA}.sessions` tied to the
API key and `mcp-session-id`. Idle TTL:
`GATEWAY_SESSION__IDLE_TTL_SECONDS` (default 24h; `0` disables). HTTP `DELETE`
with `mcp-session-id` closes the session immediately.

## Tool policy

Per-server `tools.allow` / `tools.block` (wildcards supported). Blocked tools
are removed from `tools/list`; direct `tools/call` is rejected.

## Layout

| Path | Role |
| --- | --- |
| `app/main.py` | Uvicorn factory entry |
| `app/domain/application.py` | App assembly, mounts, routes |
| `app/services/config_loader.py` | YAML scan + validation |
| `app/proxy_factory.py` | FastMCP proxy + transport |
| `app/middleware.py` | Tool policy + guard |
| `app/services/guard/` | Deterministic + LLM guard |
