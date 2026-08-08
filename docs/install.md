# Install

Requires Python **3.14+** and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-groups
cp .env.example .env   # fill tokens your YAML files reference
```

Optional frontend console:

```bash
make ui-install
make ui-build
```

Local LLM guard on Apple Silicon (Metal):

```bash
brew install ollama
ollama serve
ollama pull qwen3:4b
```

See [Configuration](configuration.md) for environment variables.
