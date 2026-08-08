# Request history UI

Build the React console, then open `http://localhost:8000/ui/` with the local
dev user:

```text
username: admin
password: changeme
```

```bash
make ui-install
make ui-build
make dev
```

`POST /api/login` issues an HttpOnly `SameSite=Lax` session cookie.
`POST /api/logout` revokes it. Change seeded credentials before non-local use.

Console shows request history for API keys owned by the signed-in user
(original/protected SQL, session metadata, PII transforms, guard decisions,
status, latency). MCP clients still use Bearer API keys.

Frontend-only: `make ui-dev` (Vite proxies `/api` to port 8000).

Compose also serves the console via Nginx at `http://localhost:5173`
(`FRONTEND_PORT` overrides). Gateway-embedded build remains at
`http://localhost:8000/ui/`.
