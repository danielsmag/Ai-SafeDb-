# Safety guard

Optional layer that combines deterministic SQL/PII checks with a local model
classification. It inspects tool arguments and results, uses validated JSON
verdicts, caches repeat decisions, redacts payloads at INFO level, and fails
closed by default.

## Enable

```dotenv
GATEWAY_GUARD__ENABLED=true
GATEWAY_LLM__BASE_URL=http://localhost:11434/v1
```

When the gateway runs in Compose on macOS, base URL defaults to
`http://host.docker.internal:11434/v1`. Linux + NVIDIA can use
`docker compose --profile llm up` (not for macOS Metal).

Per-server override in YAML:

```yaml
guard:
  enabled: true
  inspect_results: true
```

The connector uses an OpenAI-compatible API. Point `GATEWAY_LLM__BASE_URL` at
vLLM, llama.cpp, or LM Studio if needed.

## Tracing

Every tool call gets a short trace id attached to log lines as `[trace=<id>]`.
Set `GATEWAY_LOG_LEVEL=DEBUG` for nested spans (`guard.review_call`,
`llm.complete`, …). Debug logs may contain SQL, PII, or secrets — use only in
controlled environments. This is log-based, not OpenTelemetry.

## Red-team agent

```bash
uv run python -m app.agents --scenario exfiltrate-pii
# or: make agent
```

Transcripts land under `runs/` (gitignored).
