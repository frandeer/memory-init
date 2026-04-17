#!/usr/bin/env python
"""PreCompact hook. Snapshots the current turn to _buffer/ before auto-compaction.

Without this, long sessions can lose their tail when auto-compaction trims the
transcript — by the time Stop fires (if it fires at all), the detail is gone.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import llm  # noqa: E402
from memory_ops import append_buffer_turn  # noqa: E402
from stop import SUMMARY_MAX, _read_transcript, _summarize_turn, _theme_from  # noqa: E402


def main() -> int:
    # Recursion guard: if we're already inside a memory-compiler-triggered run,
    # bail out immediately so we don't fight the parent hook.
    if os.environ.get(llm.GUARD_ENV) == llm.GUARD_VALUE:
        return 0

    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}

    cwd = Path(payload.get("cwd") or os.getcwd())
    memory_dir = cwd / ".memory"
    if not memory_dir.exists():
        return 0

    session_id = payload.get("session_id") or str(uuid.uuid4())[:8]
    buffer_dir = memory_dir / "_buffer"
    buffer_dir.mkdir(exist_ok=True)
    existing = list(buffer_dir.glob(f"session-{session_id}-precompact-*.md"))
    turn_num = len(existing) + 1

    rows = _read_transcript(payload.get("transcript_path"))
    summary, user_text = _summarize_turn(rows)
    theme = _theme_from(user_text)

    if summary and user_text:
        body = f"**user:** {user_text[:SUMMARY_MAX]}\n\n**assistant:** {summary[:SUMMARY_MAX]}"
    elif summary:
        body = summary[:SUMMARY_MAX]
    elif user_text:
        body = f"**user:** {user_text[:SUMMARY_MAX]}"
    else:
        return 0

    episode = {
        "session_id": session_id,
        "turn": turn_num,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "kind": "pre-compact",
        "summary": body,
        "theme": theme,
    }
    # Reuse append_buffer_turn but tweak filename convention via turn slot —
    # the filename glob above already segregates precompact entries.
    out = buffer_dir / f"session-{session_id}-precompact-{turn_num:04d}.md"
    from memory_ops import atomic_write
    import yaml

    frontmatter_dict = {
        "session_id": session_id,
        "turn": turn_num,
        "timestamp": episode["timestamp"],
        "kind": "pre-compact",
    }
    if theme:
        frontmatter_dict["theme"] = theme
    frontmatter = yaml.safe_dump(frontmatter_dict, allow_unicode=True, sort_keys=False)
    atomic_write(out, f"---\n{frontmatter}---\n\n{body}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
