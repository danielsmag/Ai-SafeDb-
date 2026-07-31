"""Generate the JSON Schema used to validate policy YAML files."""

import json
from pathlib import Path
from typing import Final

from app.policies import SqlPolicy

SCHEMA_PATH: Final[Path] = Path("policies/policy.schema.json")


def main() -> None:
    schema: dict[str, object] = SqlPolicy.model_json_schema()
    SCHEMA_PATH.write_text(
        f"{json.dumps(schema, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
