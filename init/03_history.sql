-- Immutable audit history for gateway MCP tool calls.

CREATE TABLE IF NOT EXISTS aisafedb.tool_calls (
    id                  UUID PRIMARY KEY,
    session_id          UUID NOT NULL REFERENCES aisafedb.sessions (id),
    mcp_session_id      TEXT NOT NULL,
    api_key_id          UUID NOT NULL REFERENCES aisafedb.api_keys (id),
    api_key_name        TEXT NOT NULL,
    server_name         TEXT NOT NULL,
    tool_name           TEXT NOT NULL,
    original_arguments  JSONB NOT NULL DEFAULT '{}'::jsonb,
    original_sql        TEXT[] NOT NULL DEFAULT '{}',
    executed_sql        TEXT[] NOT NULL DEFAULT '{}',
    expanded_stars      BOOLEAN NOT NULL DEFAULT FALSE,
    dropped_columns     TEXT[] NOT NULL DEFAULT '{}',
    hashed_columns      TEXT[] NOT NULL DEFAULT '{}',
    masked_fields       TEXT[] NOT NULL DEFAULT '{}',
    removed_fields      TEXT[] NOT NULL DEFAULT '{}',
    call_decision       TEXT,
    result_decision     TEXT,
    status              TEXT NOT NULL CHECK (status IN ('ok', 'blocked', 'error')),
    error               TEXT,
    duration_ms         DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS tool_calls_api_key_created_idx
    ON aisafedb.tool_calls (api_key_id, created_at DESC);

CREATE INDEX IF NOT EXISTS tool_calls_session_id_idx
    ON aisafedb.tool_calls (session_id);

COMMENT ON TABLE aisafedb.tool_calls IS
    'Per-API-key audit history for MCP tool calls and safety transformations';
