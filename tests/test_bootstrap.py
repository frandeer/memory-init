"""Tests for bootstrap.py."""
import json
from pathlib import Path
import pytest

from bootstrap import init_project


def test_init_project_creates_structure(tmp_path):
    """init_project scaffolds .memory/ with all required dirs and files."""
    init_project(tmp_path)
    memory = tmp_path / ".memory"
    assert memory.is_dir()
    for sub in ("rules", "lessons", "patterns", "_buffer", "_archive"):
        assert (memory / sub).is_dir(), f"missing {sub}"
    for f in ("MEMORY.md", "STATE.md", "TASKS.md", ".meta.json"):
        assert (memory / f).exists(), f"missing {f}"


def test_init_project_idempotent(tmp_path):
    """Running init_project twice does not clobber existing state."""
    init_project(tmp_path)
    (tmp_path / ".memory" / "rules" / "test.md").write_text("custom content", encoding="utf-8")
    init_project(tmp_path)
    assert (tmp_path / ".memory" / "rules" / "test.md").read_text(encoding="utf-8") == "custom content"


def test_init_project_meta_json_valid(tmp_path):
    """The initial .meta.json is valid JSON."""
    init_project(tmp_path)
    meta_path = tmp_path / ".memory" / ".meta.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "created" in data
    assert "references" in data
    assert isinstance(data["references"], dict)
