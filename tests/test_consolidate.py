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
