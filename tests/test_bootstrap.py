"""Tests for bootstrap.py."""
import json
from pathlib import Path
import pytest

from bootstrap import init_project, install_global_hooks, HOOK_COMMAND_SESSION_START, HOOK_COMMAND_STOP


def test_init_project_creates_structure(tmp_path):
    """init_project scaffolds .memory/ with all required dirs and files."""
    init_project(tmp_path)
    memory = tmp_path / ".memory"
    assert memory.is_dir()
    for sub in ("rules", "lessons", "patterns", "_buffer"):
        assert (memory / sub).is_dir(), f"missing {sub}"
    # Obsolete layers should NOT be created by the minimal pipeline.
    for legacy in ("daily", "_archive", "knowledge"):
        assert not (memory / legacy).exists(), f"legacy {legacy} should not exist"
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


def test_install_global_hooks_creates_settings(tmp_path, monkeypatch):
    """install_global_hooks writes SessionStart + Stop hooks to ~/.claude/settings.json."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    (fake_home / ".claude").mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    install_global_hooks()

    settings_path = fake_home / ".claude" / "settings.json"
    assert settings_path.exists()
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})
    assert "SessionStart" in hooks
    assert "Stop" in hooks
    ss_str = json.dumps(hooks["SessionStart"])
    assert HOOK_COMMAND_SESSION_START in ss_str
    stop_str = json.dumps(hooks["Stop"])
    assert HOOK_COMMAND_STOP in stop_str


def test_install_global_hooks_preserves_existing(tmp_path, monkeypatch):
    """install_global_hooks preserves existing unrelated hooks."""
    fake_home = tmp_path / "fake_home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    existing = {
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "echo existing"}]}
            ]
        },
        "theme": "dark",
    }
    (fake_home / ".claude" / "settings.json").write_text(json.dumps(existing), encoding="utf-8")
    install_global_hooks()

    data = json.loads((fake_home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert "UserPromptSubmit" in data["hooks"]
    assert "SessionStart" in data["hooks"]
    assert "Stop" in data["hooks"]


import subprocess
import sys


def test_bootstrap_cli_init_project(tmp_path):
    """bootstrap.py init-project <path> creates .memory/."""
    script = Path(__file__).parent.parent / "scripts" / "bootstrap.py"
    result = subprocess.run(
        [sys.executable, str(script), "init-project", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".memory" / "MEMORY.md").exists()
