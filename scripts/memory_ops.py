"""File I/O utilities for the .memory/ system. Pure I/O, no business logic."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SECTIONS = ("rules", "lessons", "patterns")


@dataclass
class Entry:
    """Single memory index entry."""
    id: str
    type: str  # rule | lesson | pattern
    summary: str
    scope: str  # local | global
    updated: str
    confidence: str  # high | medium | low
    tags: list[str]
    path: str
    rationale: str | None = None
    evidence_count: int | None = None
    projects: list[str] | None = None
    supersedes: str | None = None


def parse_memory_index(memory_md_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse MEMORY.md. Returns dict with keys 'rules', 'lessons', 'patterns'.

    Each value is a list of YAML-parsed dicts. Missing sections return [].
    """
    if not memory_md_path.exists():
        return {section: [] for section in SECTIONS}

    text = memory_md_path.read_text(encoding="utf-8")
    result: dict[str, list[dict[str, Any]]] = {section: [] for section in SECTIONS}

    for section in SECTIONS:
        pattern = rf"##\s+{section.capitalize()}\s*\n+```yaml\n(.*?)```"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if not match:
            continue
        yaml_body = match.group(1).strip()
        if not yaml_body:
            continue
        try:
            parsed = yaml.safe_load(yaml_body)
        except yaml.YAMLError:
            continue
        if isinstance(parsed, list):
            result[section] = parsed

    return result


def atomic_write(target: Path, content: str) -> None:
    """Write content to target atomically (write to .tmp, then rename).

    Prevents corruption on crash during write.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def append_buffer_turn(memory_dir: Path, episode: dict[str, Any]) -> Path:
    """Write a single turn episode to _buffer/session-<id>-turn-<n>.md.

    Atomic. Unique filename per turn. Returns the written file path.
    """
    memory_dir = Path(memory_dir)
    buffer_dir = memory_dir / "_buffer"
    buffer_dir.mkdir(exist_ok=True)

    session_id = episode.get("session_id", "unknown")
    turn = episode.get("turn", 0)
    filename = f"session-{session_id}-turn-{turn:04d}.md"
    target = buffer_dir / filename

    frontmatter = yaml.safe_dump(
        {
            "session_id": session_id,
            "turn": turn,
            "timestamp": episode.get("timestamp", ""),
            "kind": episode.get("kind", "note"),
        },
        allow_unicode=True,
        sort_keys=False,
    )
    body = episode.get("summary", "")
    content = f"---\n{frontmatter}---\n\n{body}\n"

    atomic_write(target, content)
    return target


def render_memory_index(
    sections: dict[str, list[dict[str, Any]]],
    state_line: str = "",
    tasks_line: str = "",
    promotion_candidates: list[str] | None = None,
) -> str:
    """Render the MEMORY.md content from parsed sections.

    Deterministic output: given the same input, always returns the same bytes.
    """
    lines: list[str] = []
    lines.append("# Memory Index")
    lines.append("")
    lines.append("> 이 프로젝트의 장기 메모리 인덱스. `.memory/rules|lessons|patterns/` 하위에 상세 파일.")
    lines.append("")
    lines.append("## State")
    if state_line:
        lines.append(state_line)
    if tasks_line:
        lines.append(tasks_line)
    lines.append("")

    for section in SECTIONS:
        lines.append(f"## {section.capitalize()}")
        lines.append("")
        entries = sections.get(section, [])
        lines.append("```yaml")
        if entries:
            yaml_body = yaml.safe_dump(
                entries,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
            ).strip()
            lines.append(yaml_body)
        lines.append("```")
        lines.append("")

    lines.append("## Promotion Candidates")
    if promotion_candidates:
        for line in promotion_candidates:
            lines.append(line)
    lines.append("")

    return "\n".join(lines)


def _render_entry_file(entry: dict[str, Any], body: str) -> str:
    """Render a single rule/lesson/pattern .md file (frontmatter + body)."""
    fm_fields = {
        k: v for k, v in entry.items() if k != "rationale" and v is not None
    }
    fm = yaml.safe_dump(fm_fields, allow_unicode=True, sort_keys=False).strip()
    parts = [f"---\n{fm}\n---", "", f"# {entry.get('summary', entry.get('id', ''))}", "", body.strip()]
    rationale = entry.get("rationale")
    if rationale:
        parts.extend(["", "## Rationale", "", rationale.strip()])
    return "\n".join(parts) + "\n"


def write_entry(memory_dir: Path, entry: dict[str, Any], body: str) -> None:
    """Write an entry file (rules/lessons/patterns) and update MEMORY.md.

    Idempotent: calling twice with the same id updates the existing entry.
    """
    memory_dir = Path(memory_dir)
    entry_type = entry["type"]
    section = f"{entry_type}s"  # rule -> rules, etc.

    if "path" not in entry:
        safe_name = entry["id"].split(".", 1)[-1]
        entry["path"] = f"{section}/{safe_name}.md"

    target_file = memory_dir / entry["path"]
    content = _render_entry_file(entry, body)
    atomic_write(target_file, content)

    index_path = memory_dir / "MEMORY.md"
    sections = parse_memory_index(index_path)
    existing = [e for e in sections[section] if e.get("id") != entry["id"]]
    index_entry = {k: v for k, v in entry.items() if k != "rationale"}
    existing.append(index_entry)
    sections[section] = existing

    rendered = render_memory_index(sections)
    atomic_write(index_path, rendered)
