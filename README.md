# MCP Gateway

A FastAPI app that reads MCP server definitions from a dedicated folder
(`mcp-servers/`), connects to each source server (local `stdio` process or remote
`http`/`sse` endpoint), applies a per-server tool allow/block policy, and
re-exposes each one as a streamable-HTTP MCP endpoint at `/mcp/<name>`.

```
mcp-servers/github.yaml   ->  http://localhost:8000/mcp/github
mcp-servers/docs.yaml     ->  http://localhost:8000/mcp/docs
mcp-servers/postgres.yaml ->  http://localhost:8000/mcp/postgres
```

## Quick start

```bash
uv sync
cp .env.example .env          # fill in any tokens your YAML files reference
uv run uvicorn app.main:create_app --factory --reload
```

Then enable a definition in `mcp-servers/` (`enabled: true`) and restart. Check
what is mounted:

```bash
curl localhost:8000/health
curl localhost:8000/servers
```

Point an MCP client at the new URL, e.g. in `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "github-via-gateway": { "url": "http://localhost:8000/mcp/github" }
  }
}
```

## Defining a server

One YAML file per source server; see [mcp-servers/README.md](mcp-servers/README.md)
for the full field reference. A stdio example:

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

The policy is enforced in both directions: blocked tools are removed from
`tools/list`, and a direct `tools/call` for one is rejected.

## Configuration

All settings come from the environment with a `GATEWAY_` prefix (or `.env`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `GATEWAY_CONFIG_DIR` | `mcp-servers` | Folder scanned for definitions |
| `GATEWAY_MOUNT_PREFIX` | `/mcp` | Path prefix for exposed endpoints |
| `GATEWAY_PUBLIC_BASE_URL` | `http://localhost:8000` | Base URL reported by `/servers` |
| `GATEWAY_LOG_LEVEL` | `INFO` | Log level |
| `GATEWAY_STATELESS_HTTP` | `false` | Run the MCP transport without server-side sessions |
| `GATEWAY_JSON_RESPONSE` | `false` | Reply with JSON instead of SSE streams |
| `GATEWAY_ALLOWED_HOSTS` | `[]` | Extra hostnames accepted by the MCP endpoints |
| `GATEWAY_ALLOWED_ORIGINS` | `[]` | Extra origins accepted by the MCP endpoints |

Definitions are validated at startup: an invalid file, or a `${VAR}` with no
value and no `${VAR:-fallback}` default, aborts the boot with the offending file
name instead of silently serving a broken endpoint.

## Docker

```bash
docker compose up --build gateway
```

The `mcp-servers/` folder is mounted read-only, and the image includes Node.js so
`npx`-based stdio servers work.

### Postgres MCP (aisafedb)

`mcp-servers/postgres.yaml` is enabled by default and proxies the official
`@modelcontextprotocol/server-postgres` server to your Docker Postgres instance.
Start the database first, then the gateway:

```bash
docker compose up -d postgres
uv run uvicorn app.main:create_app --factory --reload
# or: docker compose up gateway
```

Connect a client to `http://localhost:8000/mcp/postgres`.

Open [`scripts/mcp_test_client.ipynb`](scripts/mcp_test_client.ipynb) with the
project's `.venv` kernel to list tools/resources and run the included read-only
Postgres query. Change `MCP_URL`, `tool_name`, or `arguments` in the notebook to
test another endpoint or tool.

To use the `mcp/postgres` Docker image directly (outside the gateway), build it
with `docker compose build postgres-mcp` and run:

```bash
docker run -i --rm --add-host=host.docker.internal:host-gateway \
  mcp/postgres postgresql://aisafe:aisafe@host.docker.internal:5432/aisafedb
```

## Layout

| Path | Role |
| --- | --- |
| [app/main.py](app/main.py) | Composition root: loads configs, mounts one MCP app per server, `/health` and `/servers` |
| [app/models.py](app/models.py) | YAML schema (`McpServerConfig`, `HttpSource`, `StdioSource`, `ToolPolicy`) |
| [app/config_loader.py](app/config_loader.py) | Folder scan, validation, `${VAR}` expansion |
| [app/proxy_factory.py](app/proxy_factory.py) | Builds a FastMCP proxy + transport per definition |
| [app/middleware.py](app/middleware.py) | Tool policy enforcement |
| [app/settings.py](app/settings.py) | Environment-driven settings |
| [app/exceptions.py](app/exceptions.py) | Error hierarchy |

## Tests

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
```
