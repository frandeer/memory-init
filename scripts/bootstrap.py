"""Bootstrap: install global hooks and initialize per-project .memory/ dirs."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"
SECTIONS = ("rules", "lessons", "patterns", "_buffer", "_archive")


def init_project(project_root: Path) -> Path:
    """Create .memory/ structure inside project_root. Idempotent.

    Returns the .memory/ directory path.
    """
    project_root = Path(project_root)
    memory = project_root / ".memory"
    memory.mkdir(parents=True, exist_ok=True)

    for sub in SECTIONS:
        (memory / sub).mkdir(exist_ok=True)

    today = datetime.date.today().isoformat()

    mem_md = memory / "MEMORY.md"
    if not mem_md.exists():
        tmpl = (TEMPLATES_DIR / "MEMORY.md.tmpl").read_text(encoding="utf-8")
        mem_md.write_text(tmpl, encoding="utf-8")

    state_md = memory / "STATE.md"
    if not state_md.exists():
        tmpl = (TEMPLATES_DIR / "STATE.md.tmpl").read_text(encoding="utf-8")
        state_md.write_text(tmpl.format(today=today), encoding="utf-8")

    tasks_md = memory / "TASKS.md"
    if not tasks_md.exists():
        tmpl = (TEMPLATES_DIR / "TASKS.md.tmpl").read_text(encoding="utf-8")
        tasks_md.write_text(tmpl, encoding="utf-8")

    meta_path = memory / ".meta.json"
    if not meta_path.exists():
        meta = {
            "created": today,
            "last_consolidated": None,
            "references": {},
            "project_tags": [],
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return memory


HOOK_COMMAND_SESSION_START = "session_start.py"
HOOK_COMMAND_STOP = "stop.py"

SESSION_START_ABS = f"python {str((SKILL_ROOT / 'scripts' / 'session_start.py').resolve())}"
STOP_ABS = f"python {str((SKILL_ROOT / 'scripts' / 'stop.py').resolve())}"


def install_global_hooks() -> Path:
    """Register SessionStart + Stop + StopFailure hooks in ~/.claude/settings.json.

    Idempotent. Preserves unrelated existing keys.
    Returns the settings.json path.
    """
    home = Path.home()
    claude_dir = home / ".claude"
    claude_dir.mkdir(exist_ok=True)
    settings_path = claude_dir / "settings.json"

    if settings_path.exists():
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        data = {}

    hooks = data.setdefault("hooks", {})

    def _ensure(event_name: str, command_abs: str, marker: str) -> None:
        existing_list = hooks.setdefault(event_name, [])
        for matcher_block in existing_list:
            for h in matcher_block.get("hooks", []):
                if marker in h.get("command", ""):
                    return
        existing_list.append(
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": command_abs,
                    }
                ],
            }
        )

    _ensure("SessionStart", SESSION_START_ABS, HOOK_COMMAND_SESSION_START)
    _ensure("Stop", STOP_ABS, HOOK_COMMAND_STOP)
    _ensure("StopFailure", STOP_ABS, HOOK_COMMAND_STOP)

    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return settings_path
