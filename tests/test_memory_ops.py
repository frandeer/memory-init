"""Tests for memory_ops.py."""
import pytest
from memory_ops import parse_memory_index


def test_parse_memory_index_empty(tmp_memory_dir):
    """빈 MEMORY.md 파싱 시 빈 sections 반환."""
    memory_md = tmp_memory_dir / "MEMORY.md"
    memory_md.write_text("# Memory Index\n\n## Rules\n\n## Lessons\n\n## Patterns\n", encoding="utf-8")
    result = parse_memory_index(memory_md)
    assert result == {"rules": [], "lessons": [], "patterns": []}


def test_parse_memory_index_with_entries(tmp_memory_dir, sample_memory_index_content):
    """entries가 있는 MEMORY.md 파싱."""
    memory_md = tmp_memory_dir / "MEMORY.md"
    memory_md.write_text(sample_memory_index_content, encoding="utf-8")
    result = parse_memory_index(memory_md)

    assert len(result["rules"]) == 1
    assert result["rules"][0]["id"] == "rule.naming.no-idx"
    assert result["rules"][0]["type"] == "rule"
    assert result["rules"][0]["summary"] == "변수명에 _idx 접미사 금지"

    assert len(result["lessons"]) == 1
    assert result["lessons"][0]["id"] == "lesson.auth.cookie"

    assert result["patterns"] == []
