import re
from typing import ClassVar, Final

from pydantic import BaseModel, ConfigDict

from app.llm import Decision

_SSN: Final[re.Pattern[str]] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL: Final[re.Pattern[str]] = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_CARD: Final[re.Pattern[str]] = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
_PII_REQUEST: Final[re.Pattern[str]] = re.compile(
    r"\b(ssn|social\s+security|credit\s+card|card_number|email|phone|"
    r"date\s+of\s+birth|dob|password|secret)\b",
    re.IGNORECASE,
)
_DESTRUCTIVE_SQL: Final[re.Pattern[str]] = re.compile(
    r"\b(insert|update|delete|drop|truncate|alter|create|grant|revoke|merge|copy)\b",
    re.IGNORECASE,
)
_SELECT: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?:with\b[\s\S]+?\bselect\b|select\b)",
    re.IGNORECASE,
)
_LIMIT: Final[re.Pattern[str]] = re.compile(r"\blimit\s+\d+\b", re.IGNORECASE)


class PrefilterVerdict(BaseModel):
    """Conclusive deterministic safety decision."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    decision: Decision
    reason: str
    confidence: float = 1.0


class PiiPrefilter:
    """Recognize direct PII requests and PII-bearing results."""

    def inspect_call(self, text: str) -> PrefilterVerdict | None:
        if _PII_REQUEST.search(text):
            return PrefilterVerdict(
                decision="block",
                reason="tool arguments request sensitive personal data",
            )
        return None

    def inspect_result(self, text: str) -> PrefilterVerdict | None:
        pii_kind: str | None = self._detect_pii(text)
        if pii_kind is not None:
            return PrefilterVerdict(
                decision="block",
                reason=f"tool result contains {pii_kind}",
            )
        return None

    @staticmethod
    def _detect_pii(text: str) -> str | None:
        if _SSN.search(text):
            return "a social security number"
        if _EMAIL.search(text):
            return "an email address"
        card_match: re.Match[str] | None = _CARD.search(text)
        if card_match is not None:
            digits: str = re.sub(r"\D", "", card_match.group(0))
            if PiiPrefilter._passes_luhn(digits):
                return "a payment-card number"
        return None

    @staticmethod
    def _passes_luhn(number: str) -> bool:
        total: int = 0
        parity: int = len(number) % 2
        for index, char in enumerate(number):
            digit: int = int(char)
            if index % 2 == parity:
                digit *= 2
                if digit > 9:
                    digit -= 9
            total += digit
        return total % 10 == 0


class SqlRiskPrefilter:
    """Block destructive SQL and unbounded top-level selects."""

    def inspect(self, text: str) -> PrefilterVerdict | None:
        if _DESTRUCTIVE_SQL.search(text):
            return PrefilterVerdict(
                decision="block",
                reason="tool arguments contain a data-changing SQL statement",
            )
        if _SELECT.search(text) and not _LIMIT.search(text):
            return PrefilterVerdict(
                decision="block",
                reason="SQL query has no explicit row limit",
            )
        return None
