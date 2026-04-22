"""Tests for memory_ops.py."""
import subprocess
import sys as _sys
import time as _t
from pathlib import Path

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
    """append_buffer_turn creates a per-event file in _buffer/ (v2 filename scheme)."""
    episode = {
        "session_id": "sess-001",
        "turn": 1,
        "hook": "Stop",
        "event_id": "abc12345",
        "timestamp": "2026-04-15T14:30:00",
        "summary": "user asked about memory system",
        "kind": "turn",
    }
    append_buffer_turn(tmp_memory_dir, episode)
    buffer_dir = tmp_memory_dir / "_buffer"
    files = [p for p in buffer_dir.glob("*.md") if not p.name.startswith(".")]
    assert len(files) == 1
    name = files[0].name
    assert "sess-001" in name or "sess001" in name
    assert "Stop" in name
    content = files[0].read_text(encoding="utf-8")
    assert "user asked about memory system" in content
    assert "event_id: abc12345" in content


def test_append_buffer_turn_idempotent(tmp_memory_dir):
    """Same event_id => second call returns the same file, no duplicate."""
    episode = {
        "session_id": "sess-002",
        "hook": "Stop",
        "event_id": "deadbeef",
        "timestamp": "2026-04-15T14:30:00",
        "summary": "first write",
        "kind": "turn",
    }
    path1 = append_buffer_turn(tmp_memory_dir, episode)
    episode_dup = dict(episode, summary="second write attempt")
    path2 = append_buffer_turn(tmp_memory_dir, episode_dup)
    assert path1 == path2
    files = [p for p in (tmp_memory_dir / "_buffer").glob("*.md") if not p.name.startswith(".")]
    assert len(files) == 1
    # Original content preserved (second write skipped)
    assert "first write" in files[0].read_text(encoding="utf-8")


from memory_ops import write_entry, render_memory_index


def test_write_entry_creates_file_and_updates_index(tmp_memory_dir):
    """write_entry writes rules/*.md and updates MEMORY.md."""
    entry = {
        "id": "rule.naming.no-idx",
        "type": "rule",
        "summary": "변수명에 _idx 접미사 금지",
        "scope": "local",
        "updated": "2026-04-15",
        "confidence": "high",
        "tags": ["naming"],
        "path": "rules/naming.md",
        "rationale": "팀 표준",
    }
    body = "변수명에 `_idx` 쓰지 마라."
    write_entry(tmp_memory_dir, entry, body)

    rule_file = tmp_memory_dir / "rules" / "naming.md"
    assert rule_file.exists()
    content = rule_file.read_text(encoding="utf-8")
    assert "변수명에 `_idx` 쓰지 마라." in content
    assert "rule.naming.no-idx" in content

    index = tmp_memory_dir / "MEMORY.md"
    assert index.exists()
    parsed = parse_memory_index(index)
    assert len(parsed["rules"]) == 1
    assert parsed["rules"][0]["id"] == "rule.naming.no-idx"


def test_render_memory_index_deterministic():
    """render_memory_index output is stable given same input."""
    sections = {
        "rules": [
            {
                "id": "rule.a",
                "type": "rule",
                "summary": "A",
                "scope": "local",
                "updated": "2026-04-15",
                "confidence": "high",
                "tags": ["x"],
                "path": "rules/a.md",
            }
        ],
        "lessons": [],
        "patterns": [],
    }
    state_line = "- STATE.md last updated 2026-04-15 — demo"
    tasks_line = "- TASKS.md: 0 pending"
    output1 = render_memory_index(sections, state_line, tasks_line)
    output2 = render_memory_index(sections, state_line, tasks_line)
    assert output1 == output2
    assert "rule.a" in output1
    assert "## Rules" in output1


from memory_ops import acquire_lock


def test_acquire_lock_creates_lockfile(tmp_path):
    """acquire_lock creates the lock file on first use."""
    lock_path = tmp_path / ".lock"
    assert not lock_path.exists()
    with acquire_lock(lock_path):
        assert lock_path.exists()
    # Still exists after release
    assert lock_path.exists()


def test_acquire_lock_sequential_works(tmp_path):
    """Sequential acquires do not deadlock or leak state."""
    lock_path = tmp_path / ".lock"
    with acquire_lock(lock_path):
        pass
    # Second acquire should succeed cleanly
    with acquire_lock(lock_path):
        pass
    # Third
    with acquire_lock(lock_path):
        pass


def test_acquire_lock_timeout_when_held_by_subprocess(tmp_path):
    """If another process holds the lock, acquire_lock raises TimeoutError."""
    lock_path = tmp_path / ".lock"
    scripts_dir = Path(__file__).parent.parent / "scripts"

    holder_script = f'''
import sys
sys.path.insert(0, r"{scripts_dir}")
from pathlib import Path
import time
from memory_ops import acquire_lock
with acquire_lock(Path(r"{lock_path}")):
    # Signal readiness by creating a flag file
    Path(r"{tmp_path}/.ready").touch()
    time.sleep(2.5)
'''
    proc = subprocess.Popen([_sys.executable, "-c", holder_script])
    try:
        # Wait for the child to signal it holds the lock
        ready_flag = tmp_path / ".ready"
        deadline = _t.monotonic() + 5.0
        while not ready_flag.exists():
            if _t.monotonic() > deadline:
                raise RuntimeError("child never signaled readiness")
            _t.sleep(0.05)

        # Now the lock is held by the child. Main process should timeout.
        start = _t.monotonic()
        with pytest.raises(TimeoutError):
            with acquire_lock(lock_path, timeout=0.4):
                pass
        elapsed = _t.monotonic() - start
        assert 0.3 < elapsed < 1.5, f"Expected ~0.4s wait, got {elapsed:.2f}s"
    finally:
        proc.wait(timeout=10)
    assert proc.returncode == 0
