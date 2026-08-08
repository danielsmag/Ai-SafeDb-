# Configuration

Settings come from the environment with a `GATEWAY_` prefix (or `.env`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `GATEWAY_CONFIG_DIR` | `mcp-servers` | Folder scanned for definitions |
| `GATEWAY_MOUNT_PREFIX` | `/mcp` | Path prefix for exposed endpoints |
| `GATEWAY_PUBLIC_BASE_URL` | `http://localhost:8000` | Base URL reported by `/servers` |
| `GATEWAY_LOG_LEVEL` | `INFO` | Log level |
| `GATEWAY_STATELESS_HTTP` | `false` | MCP transport without server-side sessions |
| `GATEWAY_JSON_RESPONSE` | `false` | JSON instead of SSE streams |
| `GATEWAY_ALLOWED_HOSTS` | `[]` | Extra hostnames for MCP endpoints |
| `GATEWAY_ALLOWED_ORIGINS` | `[]` | Extra origins for MCP endpoints |
| `GATEWAY_AUTH__SESSION_TTL_SECONDS` | `86400` | Web-console session idle TTL |
| `GATEWAY_AUTH__COOKIE_NAME` | `aisafedb_session` | Web-console session cookie name |
| `GATEWAY_AUTH__COOKIE_SECURE` | `false` | Require HTTPS for session cookie |
| `GATEWAY_GUARD__ENABLED` | (see `.env.example`) | Local LLM safety guard |
| `GATEWAY_LLM__BASE_URL` | (see `.env.example`) | OpenAI-compatible LLM endpoint |
| `GATEWAY_SESSION__IDLE_TTL_SECONDS` | `86400` | MCP session idle TTL (`0` = off) |
| `GATEWAY_DATABASE__*` / `SAFE_DB_SCHEMA` | (see `.env.example`) | DB connection + schema |

See `.env.example` for the full list including nested guard/LLM/database knobs.
