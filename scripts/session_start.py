#!/usr/bin/env python
"""SessionStart hook. Runs consolidation and injects MEMORY.md into context.

Also surfaces a hook-error summary when ``_hook_errors.jsonl`` has recent
entries, so silent Stop-hook failures don't stay invisible.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from consolidate import run_consolidation  # noqa: E402


def _recent_hook_errors(memory_dir: Path, limit: int = 3) -> list[str]:
    """Last ``limit`` dead-letter entries, one-liner summaries."""
    log = memory_dir / "_hook_errors.jsonl"
    if not log.exists():
        return []
    try:
        lines = log.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return []
    out: list[str] = []
    for raw in lines[-limit:]:
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ts = entry.get("timestamp", "")
        hook = entry.get("hook", "?")
        err = entry.get("error_type", "?")
        out.append(f"- `{ts}` {hook}: {err}")
    return out


def _rotate_hook_errors(memory_dir: Path, max_lines: int = 100, keep: int = 20) -> None:
    """Trim _hook_errors.jsonl to last ``keep`` lines if it exceeds ``max_lines``."""
    log = memory_dir / "_hook_errors.jsonl"
    if not log.exists():
        return
    try:
        all_lines = log.read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return
    if len(all_lines) > max_lines:
        log.write_text("\n".join(all_lines[-keep:]) + "\n", encoding="utf-8")


def _read_project_tags(memory_dir: Path) -> list[str]:
    """Read project_tags from .meta.json."""
    meta_path = memory_dir / ".meta.json"
    if not meta_path.exists():
        return []
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data.get("project_tags", [])
    except (json.JSONDecodeError, OSError):
        return []


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}

    cwd = Path(payload.get("cwd") or os.getcwd())
    memory_dir = cwd / ".memory"
    if not memory_dir.exists():
        return 0

    consolidation = run_consolidation(memory_dir)
    _rotate_hook_errors(memory_dir)

    index_path = memory_dir / "MEMORY.md"
    if not index_path.exists():
        return 0
    index_text = index_path.read_text(encoding="utf-8")
    lines = index_text.splitlines()
    if len(lines) > 150:
        index_text = "\n".join(lines[:150]) + "\n\n<!-- truncated at 150 lines -->"

    source = payload.get("source", "startup")
    state_text = ""
    if source in {"resume", "compact"}:
        state_path = memory_dir / "STATE.md"
        if state_path.exists():
            state_text = state_path.read_text(encoding="utf-8")

    output_parts = [
        f"# Memory index (from {memory_dir})",
        "",
    ]

    project_tags = _read_project_tags(memory_dir)
    if project_tags:
        output_parts.append(f"> Tech stack: {', '.join(project_tags)}")
        output_parts.append("")

    output_parts.append(index_text)

    if state_text:
        output_parts.extend(["", "# Current STATE", "", state_text])

    errors = _recent_hook_errors(memory_dir)
    if errors:
        output_parts.extend(["", "# Recent hook errors (dead-letter)", ""] + errors)

    if consolidation.get("promoted"):
        output_parts.append(
            f"\n<!-- consolidation: promoted={consolidation['promoted']} -->"
        )

    sys.stdout.write("\n".join(output_parts) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
