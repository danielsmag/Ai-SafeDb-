-- Gateway app state (users, API keys, browser sessions, and MCP sessions).
-- Lives in schema `aisafedb` by default (override at runtime via SAFE_DB_SCHEMA).
-- Demo MCP data stays in `public` (see 01_customers.sql).
--
-- Dev API key plaintext (local only): aisk_dev_local_00000000000000000001
-- Hash below is SHA-256 of that secret. Rotate before any non-local use.
-- Dev web login (local only): admin / changeme

CREATE SCHEMA IF NOT EXISTS aisafedb;

CREATE TABLE IF NOT EXISTS aisafedb.users (
    id            UUID PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    disabled_at   TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS aisafedb.api_keys (
    id            UUID PRIMARY KEY,
    name          TEXT NOT NULL,
    key_prefix    TEXT NOT NULL,
    key_hash      TEXT NOT NULL UNIQUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    revoked_at    TIMESTAMPTZ,
    last_used_at  TIMESTAMPTZ,
    user_id       UUID REFERENCES aisafedb.users (id)
);

CREATE TABLE IF NOT EXISTS aisafedb.web_sessions (
    id           UUID PRIMARY KEY,
    token_hash   TEXT NOT NULL UNIQUE,
    user_id      UUID NOT NULL REFERENCES aisafedb.users (id),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS web_sessions_user_id_idx
    ON aisafedb.web_sessions (user_id);

CREATE TABLE IF NOT EXISTS aisafedb.sessions (
    id              UUID PRIMARY KEY,
    mcp_session_id  TEXT NOT NULL UNIQUE,
    api_key_id      UUID NOT NULL REFERENCES aisafedb.api_keys (id),
    server_name     TEXT NOT NULL,
    data_key        TEXT NOT NULL,
    client_name     TEXT,
    client_version  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS sessions_api_key_id_idx
    ON aisafedb.sessions (api_key_id);

INSERT INTO aisafedb.users (id, username, password_hash)
VALUES (
    '00000000-0000-4000-8000-000000000010',
    'admin',
    '$2b$12$Wd.dqXEa0zXJr0MJtuywieBLWwJAxSlN1d5m/YUQcOTPIK5vlI.HC'
)
ON CONFLICT (username) DO NOTHING;

INSERT INTO aisafedb.api_keys (id, name, key_prefix, key_hash, user_id)
VALUES (
    '00000000-0000-4000-8000-000000000001',
    'local-dev',
    'aisk_dev',
    'c869076a37be0ccc37c1e36ffb64454b288ae874390783b03277f71978258183',
    '00000000-0000-4000-8000-000000000010'
)
ON CONFLICT (key_hash) DO NOTHING;

COMMENT ON SCHEMA aisafedb IS 'MCP gateway application state';
COMMENT ON TABLE aisafedb.users IS 'Web-console users';
COMMENT ON TABLE aisafedb.api_keys IS 'Hashed API keys that may open MCP sessions';
COMMENT ON TABLE aisafedb.web_sessions IS 'Server-side web-console sessions';
COMMENT ON TABLE aisafedb.sessions IS 'Recognized MCP client sessions bound to an API key';
