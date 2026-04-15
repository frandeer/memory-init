"""Tests for consolidate.py."""
import pytest
from consolidate import find_duplicates, similarity


def test_similarity_identical():
    """Identical strings have similarity 1.0."""
    assert similarity("변수명에 _idx 금지", "변수명에 _idx 금지") == 1.0


def test_similarity_very_different():
    """Unrelated strings have low similarity."""
    assert similarity("authentication issue", "database migration") < 0.3


def test_similarity_near_duplicates_high():
    """Near-duplicate strings have high similarity."""
    assert similarity(
        "변수명에 _idx 접미사를 쓰지 말 것",
        "변수명에 _idx 접미사 금지",
    ) > 0.6


def test_find_duplicates_returns_pairs_above_threshold():
    entries = [
        {"id": "a", "summary": "same thing one"},
        {"id": "b", "summary": "same thing two"},
        {"id": "c", "summary": "totally unrelated stuff"},
    ]
    pairs = find_duplicates(entries, threshold=0.6)
    assert any({"a", "b"} == set(p) for p in pairs)
    assert not any("c" in p for p in pairs)


from consolidate import detect_promotions


def test_detect_promotions_single_session_not_promoted():
    """Same theme in same session counts as 1 — not promoted."""
    buffer_episodes = [
        {"session_id": "sess-1", "summary": "retry on 5xx helped", "theme": "http-retry"},
        {"session_id": "sess-1", "summary": "retry on 5xx helped", "theme": "http-retry"},
    ]
    promotions = detect_promotions(buffer_episodes)
    assert promotions == []


def test_detect_promotions_two_independent_sessions_promoted():
    """Same theme in 2 different sessions -> promoted to pattern."""
    buffer_episodes = [
        {"session_id": "sess-1", "summary": "retry on 5xx helped", "theme": "http-retry"},
        {"session_id": "sess-2", "summary": "retry on 5xx helped", "theme": "http-retry"},
    ]
    promotions = detect_promotions(buffer_episodes)
    assert len(promotions) == 1
    assert promotions[0]["theme"] == "http-retry"
    assert promotions[0]["evidence_count"] == 2


def test_detect_promotions_theme_missing_skipped():
    """Episodes without theme are ignored."""
    buffer_episodes = [
        {"session_id": "sess-1", "summary": "noise"},
        {"session_id": "sess-2", "summary": "also noise"},
    ]
    assert detect_promotions(buffer_episodes) == []


from pathlib import Path
from memory_ops import append_buffer_turn, parse_memory_index
from consolidate import run_consolidation


def test_run_consolidation_empty_buffer_noop(tmp_memory_dir):
    """If buffer is empty, no changes are made."""
    result = run_consolidation(tmp_memory_dir)
    assert result["promoted"] == 0
    assert result["merged"] == 0


def test_run_consolidation_with_promotion(tmp_memory_dir):
    """Two independent-session buffer entries with same theme -> 1 new pattern."""
    for session_id in ("sess-1", "sess-2"):
        append_buffer_turn(
            tmp_memory_dir,
            {
                "session_id": session_id,
                "turn": 1,
                "timestamp": "2026-04-15T14:30:00",
                "summary": "retry on 5xx with jitter worked",
                "kind": "lesson",
                "theme": "http-retry-jitter",
            },
        )
    result = run_consolidation(tmp_memory_dir)
    assert result["promoted"] == 1

    index = parse_memory_index(tmp_memory_dir / "MEMORY.md")
    assert len(index["patterns"]) == 1
    assert "retry" in index["patterns"][0]["summary"]

    assert (tmp_memory_dir / "_buffer" / ".consolidated").exists()
