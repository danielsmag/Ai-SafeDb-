"""Layered deterministic and model-based MCP safety decisions."""

import hashlib
import json
import time
from collections.abc import Callable
from typing import Final

from pydantic import ValidationError

from app.core.config import GuardErrorMode
from app.core.logging import logger
from app.exceptions import LlmUnavailableError
from app.llm import ChatCompletion, ChatMessage, GuardVerdict, LlmClient
from app.services.guard.prefilter import (
    PiiPrefilter,
    PrefilterVerdict,
    SqlRiskPrefilter,
)
from app.services.guard.prompts import CALL_GUARD_PROMPT, RESULT_GUARD_PROMPT

_VERDICT_SCHEMA: Final[dict[str, object]] = GuardVerdict.model_json_schema()


class GuardService:
    """Classify MCP calls/results using deterministic checks before an LLM."""

    def __init__(
        self,
        client: LlmClient,
        model: str,
        on_error: GuardErrorMode,
        cache_ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client: LlmClient = client
        self._model: str = model
        self._on_error: GuardErrorMode = on_error
        self._cache_ttl_seconds: float = cache_ttl_seconds
        self._clock: Callable[[], float] = clock
        self._pii: PiiPrefilter = PiiPrefilter()
        self._sql: SqlRiskPrefilter = SqlRiskPrefilter()
        self._cache: dict[str, tuple[float, GuardVerdict]] = {}

    async def review_call(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, object] | None,
    ) -> GuardVerdict:
        text: str = self._serialize(arguments or {})
        deterministic: PrefilterVerdict | None = self._sql.inspect(text)
        if deterministic is None:
            deterministic = self._pii.inspect_call(text)
        if deterministic is not None:
            return self._from_prefilter(deterministic)
        subject: str = f"Server: {server_name}\nTool: {tool_name}\nArguments: {text}"
        return await self._classify("call", CALL_GUARD_PROMPT, subject)

    async def review_result(
        self,
        server_name: str,
        tool_name: str,
        result_text: str,
    ) -> GuardVerdict:
        deterministic: PrefilterVerdict | None = self._pii.inspect_result(result_text)
        if deterministic is not None:
            return self._from_prefilter(deterministic)
        subject: str = (
            f"Server: {server_name}\nTool: {tool_name}\nResult: {result_text}"
        )
        return await self._classify("result", RESULT_GUARD_PROMPT, subject)

    async def _classify(
        self,
        kind: str,
        system_prompt: str,
        subject: str,
    ) -> GuardVerdict:
        cache_key: str = self._cache_key(kind, subject)
        cached: GuardVerdict | None = self._get_cached(cache_key)
        if cached is not None:
            return cached

        started_at: float = self._clock()
        try:
            completion: ChatCompletion = await self._client.complete(
                [
                    ChatMessage(role="system", content=system_prompt),
                    ChatMessage(role="user", content=subject),
                ],
                model=self._model,
                schema=_VERDICT_SCHEMA,
            )
            content: str | None = completion.message.content
            if content is None:
                raise LlmUnavailableError("guard model returned no content")
            verdict: GuardVerdict = GuardVerdict.model_validate_json(content)
        except (LlmUnavailableError, ValidationError, ValueError) as err:
            verdict = self._error_verdict(err)

        elapsed_ms: float = (self._clock() - started_at) * 1000
        logger.info(
            "Guard verdict kind=%s model=%s decision=%s "
            "confidence=%.2f latency_ms=%.1f",
            kind,
            self._model,
            verdict.decision,
            verdict.confidence,
            elapsed_ms,
        )
        self._cache[cache_key] = (self._clock(), verdict)
        return verdict

    def _get_cached(self, key: str) -> GuardVerdict | None:
        cached: tuple[float, GuardVerdict] | None = self._cache.get(key)
        if cached is None:
            return None
        created_at: float
        verdict: GuardVerdict
        created_at, verdict = cached
        if self._clock() - created_at <= self._cache_ttl_seconds:
            return verdict
        del self._cache[key]
        return None

    def _error_verdict(self, err: Exception) -> GuardVerdict:
        logger.warning("Guard model failure: %s", type(err).__name__)
        if self._on_error == "allow":
            return GuardVerdict(
                decision="allow",
                reason="guard unavailable; fail-open policy applied",
                confidence=0,
            )
        return GuardVerdict(
            decision="block",
            reason="guard unavailable; fail-closed policy applied",
            confidence=0,
        )

    @staticmethod
    def _serialize(value: object) -> str:
        return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))

    @staticmethod
    def _cache_key(kind: str, subject: str) -> str:
        digest: str = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        return f"{kind}:{digest}"

    @staticmethod
    def _from_prefilter(verdict: PrefilterVerdict) -> GuardVerdict:
        return GuardVerdict.model_validate(verdict.model_dump())
