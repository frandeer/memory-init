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
