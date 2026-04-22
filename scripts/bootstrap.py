"""Bootstrap: install global hooks and initialize per-project .memory/ dirs."""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

SKILL_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"
SECTIONS = (
    "rules",
    "lessons",
    "patterns",
    "_buffer",
)


def init_project(project_root: Path) -> Path:
    """Create .memory/ structure inside project_root. Idempotent.

    Returns the .memory/ directory path.
    """
    project_root = Path(project_root)
    memory = project_root / ".memory"
    memory.mkdir(parents=True, exist_ok=True)

    for sub in SECTIONS:
        (memory / sub).mkdir(parents=True, exist_ok=True)

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

    _migrate_legacy_dirs(memory, today)
    return memory


LEGACY_DIRS = ("daily", "_archive", "knowledge")


def _migrate_legacy_dirs(memory: Path, today: str) -> None:
    """Move obsolete ``daily/``, ``_archive/``, ``knowledge/`` into a dated bucket.

    The minimal pipeline doesn't use these layers anymore (they required LLM
    flush/compile). Preserve any existing content under ``_migrated-<date>/``
    instead of deleting. No-op on fresh projects.
    """
    migrated_root = memory / f"_migrated-{today}"
    for name in LEGACY_DIRS:
        src = memory / name
        if not src.exists():
            continue
        try:
            if not any(src.rglob("*")):
                src.rmdir()
                continue
        except OSError:
            pass
        migrated_root.mkdir(exist_ok=True)
        dest = migrated_root / name
        if dest.exists():
            continue
        try:
            src.rename(dest)
        except OSError:
            pass


HOOK_COMMAND_SESSION_START = "session_start.py"
HOOK_COMMAND_STOP = "stop.py"
HOOK_COMMAND_PRE_COMPACT = "pre_compact.py"

# Use POSIX-style forward slashes in hook commands. On Windows, shells like
# Git Bash treat backslashes as escape characters, so `C:\Users\HP\.claude`
# gets mangled into `C:UsersHP.claude` before it reaches Python. Forward slashes
# work on Windows Python interpreters and survive shell escaping untouched.
SESSION_START_ABS = f"python {(SKILL_ROOT / 'scripts' / 'session_start.py').resolve().as_posix()}"
STOP_ABS = f"python {(SKILL_ROOT / 'scripts' / 'stop.py').resolve().as_posix()}"
PRE_COMPACT_ABS = f"python {(SKILL_ROOT / 'scripts' / 'pre_compact.py').resolve().as_posix()}"


CLAUDE_MD_BEGIN = "<!-- memory-init: BEGIN -->"
CLAUDE_MD_END = "<!-- memory-init: END -->"
CLAUDE_MD_SNIPPET = f"""{CLAUDE_MD_BEGIN}
## Memory system (memory-init)

프로젝트 루트에 `.memory/` 디렉토리가 있으면 **그 위치의 메모리 시스템을 사용**합니다.
Claude Code 기본 auto-memory(`~/.claude/projects/<slug>/memory/`)는 `.memory/`가 있는
프로젝트에서는 **쓰지 마세요** — 두 시스템 동시 운영 시 충돌/중복이 발생합니다.

- 부트스트랩: `/memory-init` 스킬
- 런타임 훅: SessionStart / Stop / StopFailure / SubagentStop / PreCompact는 `~/.claude/settings.json`에 설치됨
- 스킬 루트: `~/.claude/skills/memory-init/`
- 파일 레이아웃: `<project>/.memory/MEMORY.md`, `STATE.md`, `TASKS.md`, `rules/`, `lessons/`, `patterns/`, `_buffer/`

**한 개의 기억 레이어 (규범적):**
- **rules/lessons/patterns**: "앞으로 항상/절대 X" — `MEMORY.md`가 인덱스
- Stop/SubagentStop 훅이 `_buffer/`에 대화 턴을 적재하고, SessionStart가 반복된 패턴을 `patterns/`로 승격시킨다. LLM 호출 없음.
- 훅 실패 시 `.memory/_hook_errors.jsonl`에 dead-letter가 남고, 다음 SessionStart에 요약이 표시된다.

**메모리 쓰기 규칙:**
- `.memory/`가 있는 프로젝트: 항상 `.memory/`에 쓴다. 기본 auto-memory 경로에 쓰지 않는다.
- `.memory/`가 없는 프로젝트: 기본 auto-memory 경로를 그대로 사용한다.
{CLAUDE_MD_END}"""


def install_claude_md_override(claude_md_path: Path | None = None) -> Path:
    """Append the memory-init override section to ~/.claude/CLAUDE.md.

    Idempotent: if the BEGIN/END markers already exist, replaces the block
    with the current snippet (so updates to the snippet propagate on re-run).
    If CLAUDE.md does not exist, creates it with just the snippet.
    """
    if claude_md_path is None:
        claude_md_path = Path.home() / ".claude" / "CLAUDE.md"
    claude_md_path.parent.mkdir(parents=True, exist_ok=True)

    if claude_md_path.exists():
        existing = claude_md_path.read_text(encoding="utf-8")
    else:
        existing = ""

    if CLAUDE_MD_BEGIN in existing and CLAUDE_MD_END in existing:
        start = existing.index(CLAUDE_MD_BEGIN)
        end = existing.index(CLAUDE_MD_END) + len(CLAUDE_MD_END)
        new_content = existing[:start] + CLAUDE_MD_SNIPPET + existing[end:]
    else:
        separator = "\n\n" if existing and not existing.endswith("\n") else ("\n" if existing and not existing.endswith("\n\n") else "")
        new_content = existing + separator + CLAUDE_MD_SNIPPET + "\n"

    claude_md_path.write_text(new_content, encoding="utf-8")
    return claude_md_path


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
    _ensure("SubagentStop", STOP_ABS, HOOK_COMMAND_STOP)
    _ensure("PreCompact", PRE_COMPACT_ABS, HOOK_COMMAND_PRE_COMPACT)

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
        claude_md = install_claude_md_override()
        print(f"[memory-init] CLAUDE.md override written to {claude_md}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
