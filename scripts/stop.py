#!/usr/bin/env python
"""Stop / StopFailure hook entry. Appends this turn's episode to _buffer/."""
from __future__ import annotations

import datetime
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memory_ops import append_buffer_turn  # noqa: E402


def main() -> int:
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
    existing = list(buffer_dir.glob(f"session-{session_id}-turn-*.md"))
    turn_num = len(existing) + 1

    summary_source = ""
    transcript = payload.get("transcript") or payload.get("messages") or []
    if isinstance(transcript, list) and transcript:
        last = transcript[-1]
        if isinstance(last, dict):
            content = last.get("content") or last.get("text") or ""
            if isinstance(content, list) and content:
                content = content[0].get("text", "") if isinstance(content[0], dict) else ""
            summary_source = str(content)[:300]

    theme = ""
    user_prompt = payload.get("user_prompt") or ""
    for token in str(user_prompt).split():
        if token.startswith("#") and len(token) > 1:
            theme = token[1:]
            break

    episode = {
        "session_id": session_id,
        "turn": turn_num,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "kind": "turn",
        "summary": summary_source or "(no summary captured)",
        "theme": theme,
    }
    append_buffer_turn(memory_dir, episode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
