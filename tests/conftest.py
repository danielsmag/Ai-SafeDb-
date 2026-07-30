import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    directory: Path = tmp_path / "mcp-servers"
    directory.mkdir()
    return directory


@pytest.fixture
def write_config(config_dir: Path) -> Callable[[str, str], Path]:
    def _write(filename: str, body: str) -> Path:
        path: Path = config_dir / filename
        path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
        return path

    return _write
