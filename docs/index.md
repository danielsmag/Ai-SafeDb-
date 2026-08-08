# MCP Gateway

FastAPI app that reads MCP server definitions from `mcp-servers/`, connects to
each source (local `stdio` or remote `http`/`sse`), applies per-server tool
policy, and re-exposes each as a streamable-HTTP MCP endpoint at `/mcp/<name>`.

```text
mcp-servers/github.yaml   ->  http://localhost:8000/mcp/github
mcp-servers/docs.yaml     ->  http://localhost:8000/mcp/docs
mcp-servers/postgres.yaml ->  http://localhost:8000/mcp/postgres
```

## Why this exists

One origin for many MCP servers. Clients use a Bearer API key. Optional local
LLM guard + SQL/PII policies sit in front of tool calls so agents talk to
databases and tools more safely.

## Next steps

- [Install](install.md)
- [Quickstart](quickstart.md)
- [Gateway concepts](concepts/gateway.md)
