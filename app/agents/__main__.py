"""CLI entry point for local red-team scenarios."""

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from app.agents import RedTeamAgent, RedTeamScenario, RunEvent, ScenarioLoader
from app.core.config import AppSettings, LlmSettings
from app.llm import OpenAICompatibleLlmClient

_SCENARIO_DIR: Final[Path] = Path(__file__).parent / "scenarios"


def _parser() -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Run a bounded local-LLM red-team scenario.",
    )
    parser.add_argument(
        "--scenario",
        required=True,
        help="Scenario name from app/agents/scenarios, or a YAML path.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("runs"))
    return parser


def _scenario_path(value: str) -> Path:
    supplied: Path = Path(value)
    if supplied.suffix in {".yaml", ".yml"} or supplied.parent != Path("."):
        return supplied
    return _SCENARIO_DIR / f"{value}.yaml"


async def _run(args: argparse.Namespace) -> Path:
    settings: AppSettings = AppSettings()
    llm: LlmSettings = settings.llm
    client: OpenAICompatibleLlmClient = OpenAICompatibleLlmClient(
        base_url=llm.base_url,
        api_key=llm.api_key,
        timeout_seconds=llm.timeout_seconds,
        max_concurrency=llm.max_concurrency,
        keep_alive=llm.keep_alive,
    )
    try:
        scenario: RedTeamScenario = ScenarioLoader().load(_scenario_path(args.scenario))
        agent: RedTeamAgent = RedTeamAgent(client, model=llm.agent_model)
        events: list[RunEvent] = await agent.run(scenario)
    finally:
        await client.close()

    output_dir: Path = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp: str = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_path: Path = output_dir / f"{scenario.name}-{stamp}.jsonl"
    payload: str = "\n".join(event.model_dump_json() for event in events) + "\n"
    output_path.write_text(payload, encoding="utf-8")
    return output_path


def main() -> None:
    args: argparse.Namespace = _parser().parse_args()
    output_path: Path = asyncio.run(_run(args))
    print(output_path)


if __name__ == "__main__":
    main()
