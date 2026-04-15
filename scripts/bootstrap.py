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
