"""Tests for flush.py — LLM is mocked; we only verify the plumbing."""
from pathlib import Path

import pytest

import flush
import llm
from memory_ops import append_buffer_turn


def _seed_buffer(memory_dir: Path, session: str, turn: int, summary: str, theme: str = "") -> None:
    append_buffer_turn(
        memory_dir,
        {
            "session_id": session,
            "turn": turn,
            "timestamp": "2026-04-17T10:00:00",
            "kind": "turn",
            "summary": summary,
            "theme": theme,
        },
    )


def test_flush_skips_when_llm_unavailable(tmp_memory_dir, monkeypatch):
    """No API key -> flush is a silent no-op. Buffer stays untouched."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _seed_buffer(tmp_memory_dir, "sess-1", 1, "some decision")
    result = flush.run_flush(tmp_memory_dir)
    assert result["skipped"] == 1
    assert not (tmp_memory_dir / "_buffer" / ".flushed").exists()
    assert not (tmp_memory_dir / "daily").glob("*.md") or not any((tmp_memory_dir / "daily").iterdir())


def test_flush_writes_daily_and_marks_sentinel(tmp_memory_dir, monkeypatch):
    """LLM returns text -> daily/YYYY-MM-DD.md gets the section and .flushed sentinel is set."""
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(
        llm,
        "call",
        lambda system, user, **_: "- decision: shipped the flush pipeline",
    )

    _seed_buffer(tmp_memory_dir, "sess-A", 1, "user wanted X", theme="flush")
    _seed_buffer(tmp_memory_dir, "sess-A", 2, "we implemented Y", theme="flush")

    result = flush.run_flush(tmp_memory_dir)
    assert result["flushed"] == 1
    assert (tmp_memory_dir / "_buffer" / ".flushed").exists()

    daily_files = list((tmp_memory_dir / "daily").glob("*.md"))
    assert len(daily_files) == 1
    text = daily_files[0].read_text(encoding="utf-8")
    assert "sess-A" in text
    assert "shipped the flush pipeline" in text


def test_flush_empty_buffer_no_write(tmp_memory_dir, monkeypatch):
    """Nothing to flush -> no daily file created."""
    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "call", lambda *a, **k: "should not be called")
    result = flush.run_flush(tmp_memory_dir)
    assert result["episodes_seen"] == 0
    assert not list((tmp_memory_dir / "daily").glob("*.md"))


def test_flush_sentinel_is_independent_from_consolidate(tmp_memory_dir, monkeypatch):
    """Running consolidate first must NOT prevent flush from seeing the same episodes."""
    from consolidate import run_consolidation

    _seed_buffer(tmp_memory_dir, "sess-1", 1, "decision A", theme="shared")
    _seed_buffer(tmp_memory_dir, "sess-2", 1, "decision A", theme="shared")

    # consolidate touches .consolidated
    run_consolidation(tmp_memory_dir)
    assert (tmp_memory_dir / "_buffer" / ".consolidated").exists()

    # flush should still see those same episodes via its own .flushed sentinel
    captured = {}

    def fake_call(system, user, **_):
        captured["user"] = user
        return "- decision: saw both sessions"

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "call", fake_call)

    result = flush.run_flush(tmp_memory_dir)
    assert result["episodes_seen"] == 2
    assert "decision A" in captured["user"]
