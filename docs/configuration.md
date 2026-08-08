# Configuration

Settings load in this order (later sources win only when earlier ones omit a
value; earlier sources override later ones):

1. Constructor kwargs
2. Process environment (`GATEWAY_*`)
3. `.env`
4. `settings.toml` (committed non-secret defaults)
5. Field defaults in code

Secrets (DB password, tokens, API keys) stay in `.env` / the environment.
Tune models, guard policy, TTLs, and paths in `settings.toml`.

## `settings.toml`

| Key | Default | Purpose |
| --- | --- | --- |
| `config_dir` | `mcp-servers` | Folder scanned for MCP definitions |
| `policies_dir` | `policies` | Policy YAML folder |
| `pipelines_dir` | `pipelines` | Pipeline YAML folder |
| `workflows_dir` | `workflows` | Workflow YAML folder |
| `sources_dir` | `sources` | Source YAML folder |
| `outputs_dir` | `outputs` | Output YAML folder |
| `mount_prefix` | `/mcp` | Path prefix for exposed MCP endpoints |
| `public_base_url` | `http://localhost:8000` | Base URL reported by `/servers` |
| `log_level` | `INFO` | Log level |
| `stateless_http` | `false` | MCP transport without server-side sessions |
| `json_response` | `false` | JSON instead of SSE streams |
| `allowed_hosts` | `[]` | Extra hostnames for MCP endpoints |
| `allowed_origins` | `[]` | Extra origins for MCP endpoints |
| `llm.*` | (see file) | Models, timeouts, concurrency |
| `guard.*` | (see file) | Local LLM safety guard |
| `session.idle_ttl_seconds` | `86400` | MCP session idle TTL (`0` = off) |
| `auth.*` | (see file) | Web-console cookie session |
| `pipeline.*` | (see file) | Task parallelism, timeout, retries |

## Environment overrides

Any `settings.toml` key can be overridden with `GATEWAY_` and nested `__`
(for example `GATEWAY_GUARD__ENABLED=true`, `GATEWAY_LLM__BASE_URL=...`).

| Variable | Purpose |
| --- | --- |
| `GATEWAY_DATABASE__*` / `SAFE_DB_SCHEMA` | DB connection + schema (prefer env) |
| `GATEWAY_LLM__API_KEY` | LLM API key when the endpoint requires one |
| `GATEWAY_LLM__BASE_URL` | OpenAI-compatible LLM endpoint (Docker sets host gateway) |

See `.env.example` for secrets and deploy-specific overrides.
