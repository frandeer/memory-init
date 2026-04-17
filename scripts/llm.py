"""Agent SDK wrapper. Single choke point for all LLM calls.

Every module that talks to the Anthropic API goes through here so the
recursion guard and availability check live in exactly one place.
"""
from __future__ import annotations

import os

GUARD_ENV = "CLAUDE_INVOKED_BY"
GUARD_VALUE = "memory-compiler"
DEFAULT_MODEL = "claude-sonnet-4-6"


def is_available() -> bool:
    """True when we can safely call the Anthropic SDK.

    False if: anthropic package missing, API key absent, or we're already
    running inside a memory-compiler-triggered LLM call (recursion guard).
    """
    if os.environ.get(GUARD_ENV) == GUARD_VALUE:
        return False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def call(system: str, user: str, model: str = DEFAULT_MODEL, max_tokens: int = 2048) -> str | None:
    """Single-turn Anthropic call. Returns response text or None on any failure.

    Sets CLAUDE_INVOKED_BY=memory-compiler before the call so any child Claude
    Code session triggered by this process short-circuits its own hooks.
    """
    if not is_available():
        return None

    os.environ[GUARD_ENV] = GUARD_VALUE
    try:
        import anthropic

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = []
        for block in response.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        return "\n".join(parts).strip() or None
    except Exception:
        return None
