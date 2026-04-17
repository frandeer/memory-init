"""Tests for the llm.py recursion guard and availability check."""
import llm


def test_guard_env_disables_availability(monkeypatch):
    """CLAUDE_INVOKED_BY=memory-compiler must short-circuit is_available()."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setenv(llm.GUARD_ENV, llm.GUARD_VALUE)
    assert llm.is_available() is False


def test_missing_api_key_disables_availability(monkeypatch):
    """No ANTHROPIC_API_KEY -> is_available returns False."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv(llm.GUARD_ENV, raising=False)
    assert llm.is_available() is False


def test_call_returns_none_when_unavailable(monkeypatch):
    """call() must return None (not raise) when is_available is False."""
    monkeypatch.setenv(llm.GUARD_ENV, llm.GUARD_VALUE)
    assert llm.call("sys", "user") is None
