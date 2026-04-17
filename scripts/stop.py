#!/usr/bin/env python
"""Stop / StopFailure hook entry. Appends this turn's episode to _buffer/."""
from __future__ import annotations

import datetime
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from memory_ops import append_buffer_turn  # noqa: E402

SUMMARY_MAX = 500


def _extract_text_blocks(content: Any) -> str:
    """Pull readable text out of a message.content payload.

    Claude Code transcript content blocks come in several shapes:
    - plain string
    - list of {type: "text", text: ...} blocks (assistant prose)
    - list containing tool_use / tool_result / thinking blocks (skipped)
    """
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        elif btype is None and isinstance(block.get("text"), str):
            parts.append(block["text"].strip())
    return "\n".join(parts).strip()


def _is_tool_result_only(content: Any) -> bool:
    """User entries that are pure tool_result echoes shouldn't count as user prompts."""
    if not isinstance(content, list) or not content:
        return False
    return all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def _read_transcript(transcript_path: str | None) -> list[dict[str, Any]]:
    if not transcript_path:
        return []
    path = Path(transcript_path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows


def _summarize_turn(rows: list[dict[str, Any]]) -> tuple[str, str]:
    """Walk transcript backwards: last assistant text → summary, last user text → theme source."""
    summary = ""
    user_text = ""
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        rtype = row.get("type")
        msg = row.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if rtype == "assistant" and not summary:
            text = _extract_text_blocks(content)
            if text:
                summary = text
        elif rtype == "user" and not user_text:
            if _is_tool_result_only(content):
                continue
            text = _extract_text_blocks(content)
            if text:
                user_text = text
        if summary and user_text:
            break
    return summary, user_text


def _theme_from(user_text: str) -> str:
    for token in user_text.split():
        if token.startswith("#") and len(token) > 1:
            return token[1:].strip(".,;:!?")
    return ""


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
        # Nothing to capture (e.g. transcript missing) — skip stub creation.
        return 0

    episode = {
        "session_id": session_id,
        "turn": turn_num,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "kind": "turn",
        "summary": body,
        "theme": theme,
    }
    append_buffer_turn(memory_dir, episode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
