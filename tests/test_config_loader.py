from collections.abc import Callable
from pathlib import Path

import pytest

from app.exceptions import ConfigError, DuplicateServerError, MissingEnvVarError
from app.models import HttpSource, McpServerConfig, StdioSource
from app.services.config_loader import ConfigLoader


def test_loads_http_and_stdio_definitions(
    config_dir: Path,
    write_config: Callable[[str, str], Path],
) -> None:
    write_config(
        "docs.yaml",
        """
        source:
          transport: http
          url: https://mcp.example.com/mcp
          headers:
            Authorization: Bearer ${DOCS_TOKEN}
        tools:
          allow: [search_*]
        """,
    )
    write_config(
        "local.yml",
        """
        name: local
        source:
          transport: stdio
          command: npx
          args: ["-y", "some-server"]
        """,
    )

    configs: list[McpServerConfig] = ConfigLoader(
        config_dir, environ={"DOCS_TOKEN": "secret"}
    ).load()

    assert [config.name for config in configs] == ["docs", "local"]
    docs: McpServerConfig = configs[0]
    local: McpServerConfig = configs[1]
    assert isinstance(docs.source, HttpSource)
    assert docs.source.headers["Authorization"] == "Bearer secret"
    assert docs.tools.allow == ["search_*"]
    assert isinstance(local.source, StdioSource)
    assert local.source.args == ["-y", "some-server"]


def test_name_defaults_to_file_stem(
    config_dir: Path,
    write_config: Callable[[str, str], Path],
) -> None:
    write_config(
        "my-server.yaml",
        """
        source:
          transport: stdio
          command: ./server.py
        """,
    )

    configs: list[McpServerConfig] = ConfigLoader(config_dir, environ={}).load()

    assert configs[0].name == "my-server"


def test_disabled_definitions_are_skipped(
    config_dir: Path,
    write_config: Callable[[str, str], Path],
) -> None:
    write_config(
        "off.yaml",
        """
        enabled: false
        source:
          transport: stdio
          command: ./server.py
        """,
    )

    assert ConfigLoader(config_dir, environ={}).load() == []


def test_env_placeholder_fallback(
    config_dir: Path,
    write_config: Callable[[str, str], Path],
) -> None:
    write_config(
        "docs.yaml",
        """
        source:
          transport: http
          url: ${DOCS_URL:-https://fallback.example.com/mcp}
        """,
    )

    configs: list[McpServerConfig] = ConfigLoader(config_dir, environ={}).load()
    source: HttpSource | StdioSource = configs[0].source

    assert isinstance(source, HttpSource)
    assert str(source.url) == "https://fallback.example.com/mcp"


def test_missing_env_var_fails_fast(
    config_dir: Path,
    write_config: Callable[[str, str], Path],
) -> None:
    write_config(
        "docs.yaml",
        """
        source:
          transport: http
          url: https://mcp.example.com/mcp
          headers:
            Authorization: Bearer ${ABSENT_TOKEN}
        """,
    )

    with pytest.raises(MissingEnvVarError) as err:
        ConfigLoader(config_dir, environ={}).load()

    assert err.value.var_name == "ABSENT_TOKEN"


def test_unknown_field_is_rejected(
    config_dir: Path,
    write_config: Callable[[str, str], Path],
) -> None:
    write_config(
        "docs.yaml",
        """
        source:
          transport: http
          url: https://mcp.example.com/mcp
        tolls:
          allow: []
        """,
    )

    with pytest.raises(ConfigError):
        ConfigLoader(config_dir, environ={}).load()


def test_duplicate_names_are_rejected(
    config_dir: Path,
    write_config: Callable[[str, str], Path],
) -> None:
    for filename in ("a.yaml", "b.yaml"):
        write_config(
            filename,
            """
            name: same
            source:
              transport: stdio
              command: ./server.py
            """,
        )

    with pytest.raises(DuplicateServerError):
        ConfigLoader(config_dir, environ={}).load()


def test_missing_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        ConfigLoader(tmp_path / "nope", environ={}).load()
