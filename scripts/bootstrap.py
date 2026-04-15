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

# Use POSIX-style forward slashes in hook commands. On Windows, shells like
# Git Bash treat backslashes as escape characters, so `C:\Users\HP\.claude`
# gets mangled into `C:UsersHP.claude` before it reaches Python. Forward slashes
# work on Windows Python interpreters and survive shell escaping untouched.
SESSION_START_ABS = f"python {(SKILL_ROOT / 'scripts' / 'session_start.py').resolve().as_posix()}"
STOP_ABS = f"python {(SKILL_ROOT / 'scripts' / 'stop.py').resolve().as_posix()}"


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


def _detect_project_tags(project_root: Path) -> list[str]:
    """Sniff common build files to detect tech stack tags."""
    tags: list[str] = []
    markers = {
        "package.json": "node",
        "pyproject.toml": "python",
        "requirements.txt": "python",
        "Cargo.toml": "rust",
        "go.mod": "go",
        "build.gradle": "java",
        "pom.xml": "java",
    }
    for fname, tag in markers.items():
        if (project_root / fname).exists() and tag not in tags:
            tags.append(tag)
    return tags


def _update_project_tags(memory_dir: Path, project_root: Path) -> None:
    meta_path = memory_dir / ".meta.json"
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["project_tags"] = _detect_project_tags(project_root)
    meta_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init-project", help="Initialize .memory/ in a project")
    init_p.add_argument("path", type=Path, help="Project root")

    sub.add_parser("install-global", help="Install SessionStart + Stop hooks globally")

    args = parser.parse_args(argv)

    if args.command == "init-project":
        memory = init_project(args.path)
        _update_project_tags(memory, args.path)
        print(f"[memory-init] initialized {memory}")
        return 0

    if args.command == "install-global":
        settings = install_global_hooks()
        print(f"[memory-init] global hooks installed at {settings}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
