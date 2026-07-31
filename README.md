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

## Local LLM safety guard

The optional guard layers deterministic SQL/PII checks with a local model
classification. It inspects both tool arguments and results, uses validated JSON
verdicts, caches repeat decisions, redacts payloads from logs, and fails closed
by default.

On Apple Silicon, install and run Ollama on the host so it can use Metal. Docker
Desktop cannot pass the Mac GPU into an Ollama container:

```bash
brew install ollama
ollama serve
ollama pull qwen3:4b
ollama pull qwen3.6:35b-a3b
```

Enable the guard in `.env`:

```dotenv
GATEWAY_GUARD__ENABLED=true
GATEWAY_LLM__BASE_URL=http://localhost:11434/v1
```

When the gateway itself runs in Compose, its base URL defaults to
`http://host.docker.internal:11434/v1`. Linux hosts with an NVIDIA GPU can
instead run `docker compose --profile llm up`; that profile is intentionally
not suitable for macOS.

Per-server behavior can override global settings:

```yaml
guard:
  enabled: true
  inspect_results: true
```

The connector uses the OpenAI-compatible API rather than an Ollama-specific
SDK. To use vLLM, llama.cpp, or LM Studio later, change
`GATEWAY_LLM__BASE_URL`.

### Red-team agent

With the gateway and Ollama running, execute the included bounded PII
exfiltration scenario:

```bash
uv run python -m app.agents --scenario exfiltrate-pii
```

The agent obtains tool schemas from `/mcp/postgres`, never connects directly to
Postgres, and writes a JSONL audit transcript under `runs/`. Scenario files set
hard step and wall-clock limits. Use `GATEWAY_LLM__AGENT_MODEL` to select the
tool-calling model. Transcripts may contain sensitive test data; `runs/` is
gitignored and should be handled as restricted audit output.

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
| [app/main.py](app/main.py) | Thin Uvicorn application-factory entry point |
| [app/core/bootstrap.py](app/core/bootstrap.py) | Startup sequence for logging, dependency wiring, and app assembly |
| [app/core/container.py](app/core/container.py) | Dependency-injector providers and dependency lifetimes |
| [app/core/config.py](app/core/config.py) | Validated, environment-driven Pydantic settings |
| [app/domain/gateway_application.py](app/domain/gateway_application.py) | Loads configs, mounts MCP apps, and registers gateway routes |
| [app/models/models.py](app/models/models.py) | YAML schema (`McpServerConfig`, `HttpSource`, `StdioSource`, `ToolPolicy`) |
| [app/services/config_loader.py](app/services/config_loader.py) | Folder scan, validation, `${VAR}` expansion |
| [app/proxy_factory.py](app/proxy_factory.py) | Builds a FastMCP proxy + transport per definition |
| [app/middleware.py](app/middleware.py) | Tool policy and LLM guard enforcement |
| [app/connectors/llm/](app/connectors/llm/) | OpenAI-compatible local-model adapter |
| [app/services/guard/](app/services/guard/) | Deterministic prefilters and layered guard service |
| [app/agents/](app/agents/) | Bounded red-team agent and scenarios |
| [app/exceptions/](app/exceptions/) | Gateway error hierarchy |

## Tests

```bash
uv sync --all-groups
uv run pytest
uv run ruff check .
```
