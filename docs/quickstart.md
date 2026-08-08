# Quickstart

## Run the gateway

```bash
uv run uvicorn app.main:create_app --factory --reload
# or: make dev
```

Enable a definition in `mcp-servers/` (`enabled: true`) and restart. Check
what is mounted:

```bash
curl localhost:8000/health
curl localhost:8000/servers
```

## Connect an MCP client

Local seed key (dev only): `aisk_dev_local_00000000000000000001`.

=== "Cursor / JSON"

    ```json
    {
      "mcpServers": {
        "github-via-gateway": {
          "url": "http://localhost:8000/mcp/github",
          "headers": {
            "Authorization": "Bearer aisk_dev_local_00000000000000000001"
          }
        }
      }
    }
    ```

=== "Python / FastMCP"

    ```python
    from fastmcp import Client

    async with Client(
        "http://localhost:8000/mcp/postgres",
        auth="aisk_dev_local_00000000000000000001",
    ) as client:
        tools = await client.list_tools()
    ```

Each successful connect opens a row in `{SAFE_DB_SCHEMA}.sessions` bound to the
API key and MCP `mcp-session-id`.

## Postgres example

```bash
docker compose up -d postgres
uv run uvicorn app.main:create_app --factory --reload
```

Point a client at `http://localhost:8000/mcp/postgres`. Notebook:
`scripts/mcp_test_client.ipynb`.
