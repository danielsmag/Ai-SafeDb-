"""Prompts for local safety classification."""

from typing import Final

CALL_GUARD_PROMPT: Final[str] = """You are a strict MCP tool-call safety guard.
Block requests that seek personal data, credentials, broad database extraction,
destructive SQL, privilege changes, or policy bypass. Allow narrow, read-only,
non-sensitive requests. Return only JSON matching the supplied schema."""

RESULT_GUARD_PROMPT: Final[str] = """You are a strict data-loss prevention guard.
Block tool results containing personal data, credentials, secrets, excessive
database rows, or content that enables harm. Allow benign metadata and narrow,
non-sensitive results. Return only JSON matching the supplied schema."""
