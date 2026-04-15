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


from memory_ops import atomic_write, append_buffer_turn


def test_atomic_write_creates_file(tmp_path):
    """atomic_write creates the file with the given content."""
    target = tmp_path / "x.md"
    atomic_write(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_overwrites_safely(tmp_path):
    """atomic_write does not leave partial data on overwrite."""
    target = tmp_path / "x.md"
    atomic_write(target, "first")
    atomic_write(target, "second")
    assert target.read_text() == "second"
    leftover = [p for p in tmp_path.iterdir() if p.name != "x.md"]
    assert leftover == []


def test_append_buffer_turn_writes_unique_file(tmp_memory_dir):
    """append_buffer_turn creates a per-turn file in _buffer/."""
    episode = {
        "session_id": "sess-001",
        "turn": 1,
        "timestamp": "2026-04-15T14:30:00",
        "summary": "user asked about memory system",
        "kind": "request",
    }
    append_buffer_turn(tmp_memory_dir, episode)
    buffer_dir = tmp_memory_dir / "_buffer"
    files = list(buffer_dir.glob("session-sess-001-turn-*.md"))
    assert len(files) == 1
    content = files[0].read_text()
    assert "user asked about memory system" in content
