# Docker

```bash
docker compose up --build gateway
```

`mcp-servers/` is mounted read-only. Image includes Node.js for `npx`-based
stdio servers.

## Docs site

MkDocs builds into a static Nginx image (same pattern as the frontend):

```bash
docker compose up --build docs
```

Open `http://localhost:8001` (`DOCS_PORT` overrides the host port).

## Postgres + gateway

```bash
docker compose up -d postgres
docker compose up gateway
# or host process: make dev
```

Connect to `http://localhost:8000/mcp/postgres`.

## Standalone postgres MCP image

```bash
docker compose build postgres-mcp
docker run -i --rm --add-host=host.docker.internal:host-gateway \
  mcp/postgres postgresql://aisafe:aisafe@host.docker.internal:5432/aisafedb
```
