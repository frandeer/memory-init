#!/usr/bin/env python
"""Stop / StopFailure / SubagentStop hook entry.

Writes one event to ``.memory/_buffer/`` per firing. Design goals:

- **No data loss**: every exception falls through ``safe_main`` and lands in
  ``_hook_errors.jsonl`` instead of killing the turn file.
- **Race-proof filenames**: ``memory_ops.append_buffer_turn`` uses
  ``ts_ns + hash`` so concurrent firings never collide.
- **Tool metadata preserved**: ``_extract_blocks_v2`` records file paths and
  commands from Edit/Write/Bash so a long autonomous fix is represented,
  not just the final summary text.
- **Subagent hybrid**: SubagentStop fires produce ``kind: subagent_turn``
  files. The parent ``Stop`` folds child ``event_id``s into its frontmatter
  and embeds 100-char summaries in the body.
"""
from __future__ import annotations

import datetime
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

from memory_ops import (  # noqa: E402
    append_buffer_turn,
    append_hook_error,
    compute_event_id,
    mark_consumed,
    parse_buffer_file,
)

SUMMARY_MAX = 8192
HEAD_TAIL_LEN = 3800  # bytes each side when truncating
TOOL_EXCERPT_MAX = 240
FILE_PATH_MAX = 200


def _extract_blocks_v2(content: Any) -> dict[str, Any]:
    """Pull text and tool metadata from a ``message.content`` payload.

    Returns ``{"text": str, "tools": list[dict]}`` where each tool dict has
    ``{"tool": name, "id"?, "file_path"?, "command"?, "pattern"?}`` for
    tool_use blocks or ``{"tool_result": id, "is_error": bool}`` for results.
    """
    if isinstance(content, str):
        return {"text": content.strip(), "tools": []}
    if not isinstance(content, list):
        return {"text": "", "tools": []}
    text_parts: list[str] = []
    tools: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text", "")
            if isinstance(t, str) and t.strip():
                text_parts.append(t.strip())
        elif btype is None and isinstance(block.get("text"), str):
            text_parts.append(block["text"].strip())
        elif btype == "tool_use":
            tools.append(_tool_use_meta(block))
        elif btype == "tool_result":
            meta = _tool_result_meta(block)
            if meta:
                tools.append(meta)
    return {"text": "\n".join(text_parts).strip(), "tools": tools}


def _tool_use_meta(block: dict[str, Any]) -> dict[str, Any]:
    """Minimal metadata — no excerpts, just the identifiers a dev needs to recall a fix."""
    name = block.get("name", "unknown")
    tool_id = block.get("id") or ""
    meta: dict[str, Any] = {"tool": name, "id": tool_id[:16]}
    inp = block.get("input") or {}
    if not isinstance(inp, dict):
        return meta
    for key in ("file_path", "path", "notebook_path"):
        if key in inp:
            meta["file_path"] = str(inp[key])[:FILE_PATH_MAX]
            break
    if "command" in inp:
        meta["command"] = str(inp["command"])[:TOOL_EXCERPT_MAX]
    if "pattern" in inp:
        meta["pattern"] = str(inp["pattern"])[:120]
    return meta


def _tool_result_meta(block: dict[str, Any]) -> dict[str, Any] | None:
    """Extract error flag from tool_result. Returns None if nothing useful."""
    tool_use_id = block.get("tool_use_id", "")
    is_error = block.get("is_error")
    if tool_use_id and (is_error is not None):
        return {"tool_result": tool_use_id[:16], "is_error": bool(is_error)}
    return None


def _is_tool_result_only(content: Any) -> bool:
    """User entries that are pure tool_result echoes shouldn't count as prompts."""
    if not isinstance(content, list) or not content:
        return False
    return all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


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


def _head_tail_truncate(text: str, limit: int = SUMMARY_MAX) -> str:
    if len(text) <= limit:
        return text
    head = text[:HEAD_TAIL_LEN]
    tail = text[-HEAD_TAIL_LEN:]
    return f"{head}\n\n[... truncated {len(text) - 2 * HEAD_TAIL_LEN} chars ...]\n\n{tail}"


def _summarize_turn(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Walk rows backward to capture one logical turn.

    Returns ``{user_text, assistant_text, tools, last_uuid}``. Assistant text
    concatenates every text block since the last user prompt (so multi-message
    fix narrations survive). Tools aggregates every tool_use/result in that
    window.
    """
    last_uuid = ""
    user_text = ""
    assistant_parts: list[str] = []
    tools: list[dict[str, Any]] = []
    collected_user = False
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        if not last_uuid:
            last_uuid = row.get("uuid") or ""
        rtype = row.get("type")
        msg = row.get("message") or {}
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if rtype == "user":
            if _is_tool_result_only(content):
                blocks = _extract_blocks_v2(content)
                tools = blocks["tools"] + tools
                continue
            if collected_user:
                break
            blocks = _extract_blocks_v2(content)
            if blocks["text"]:
                user_text = blocks["text"]
                collected_user = True
        elif rtype == "assistant":
            blocks = _extract_blocks_v2(content)
            if blocks["text"]:
                assistant_parts.append(blocks["text"])
            tools = blocks["tools"] + tools
    return {
        "user_text": user_text,
        "assistant_text": "\n\n".join(reversed(assistant_parts)).strip(),
        "tools": tools,
        "last_uuid": last_uuid,
    }


def _theme_from(user_text: str) -> str:
    for token in (user_text or "").split():
        if token.startswith("#") and len(token) > 1:
            return token[1:].strip(".,;:!?")
    return ""


def _render_tools_section(tools: list[dict[str, Any]]) -> str:
    if not tools:
        return ""
    lines = ["## Tools", ""]
    for t in tools:
        if "tool" in t:
            parts = [f"- **{t['tool']}**"]
            if t.get("file_path"):
                parts.append(f"`{t['file_path']}`")
            if t.get("command"):
                parts.append(f"`{t['command']}`")
            if t.get("pattern"):
                parts.append(f"/{t['pattern']}/")
            lines.append(" ".join(parts))
        elif "tool_result" in t:
            status = "ERROR" if t.get("is_error") else "ok"
            lines.append(f"  → result {t['tool_result']}: {status}")
    return "\n".join(lines)


def _collect_child_refs(
    memory_dir: Path, session_id: str
) -> tuple[list[str], list[str], list[Path]]:
    """Find **unconsumed** ``subagent_turn`` entries whose parent is this session.

    Returns ``(event_ids, summary_lines, paths)``. The caller writes event_ids
    into the parent turn's frontmatter, embeds summary_lines in the body, and
    marks ``paths`` consumed so later Stops in the same session don't re-fold
    the same children in again.
    """
    buffer_dir = memory_dir / "_buffer"
    if not buffer_dir.exists():
        return [], [], []
    refs: list[str] = []
    summaries: list[str] = []
    paths: list[Path] = []
    for path in sorted(buffer_dir.glob("*.md")):
        parsed = parse_buffer_file(path)
        if parsed is None:
            continue
        fm, body = parsed
        if fm.get("kind") != "subagent_turn":
            continue
        if fm.get("parent_session_id") != session_id:
            continue
        if fm.get("consumed"):
            continue
        event_id = fm.get("event_id") or ""
        if not event_id:
            continue
        refs.append(event_id)
        first_line = body.splitlines()[0] if body else ""
        summaries.append(f"- `{event_id}`: {first_line[:100]}")
        paths.append(path)
    return refs, summaries, paths


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}

    cwd = Path(payload.get("cwd") or os.getcwd())
    memory_dir = cwd / ".memory"
    if not memory_dir.exists():
        return 0

    session_id = payload.get("session_id") or "unknown"
    hook_event = payload.get("hook_event_name") or "Stop"
    transcript_path = payload.get("transcript_path")

    try:
        transcript_size = Path(transcript_path).stat().st_size if transcript_path else 0
    except OSError:
        transcript_size = 0

    rows = _read_transcript(transcript_path)
    summ = _summarize_turn(rows)

    user_text = summ["user_text"]
    assistant_text = summ["assistant_text"]
    tools = summ["tools"]

    if not (user_text or assistant_text or tools):
        return 0

    event_id = compute_event_id(
        session_id=session_id,
        hook=hook_event,
        transcript_path=transcript_path,
        transcript_size=transcript_size,
        last_uuid=summ["last_uuid"],
    )

    body_parts: list[str] = []
    if user_text:
        body_parts.append(f"**user:** {_head_tail_truncate(user_text)}")
    if assistant_text:
        body_parts.append(f"**assistant:** {_head_tail_truncate(assistant_text)}")
    tools_section = _render_tools_section(tools)
    if tools_section:
        body_parts.append(tools_section)

    if hook_event == "SubagentStop":
        kind = "subagent_turn"
    elif hook_event == "PreCompact":
        kind = "pre_compact"
    else:
        kind = "turn"
    # For subagents, payload.session_id IS the parent session (Claude Code
    # shares session_id across parent + subagent Stops). Use that as the link.
    parent_session_id = session_id if kind == "subagent_turn" else None
    child_refs: list[str] = []

    child_paths: list[Path] = []
    if kind == "turn":
        refs, child_summaries, child_paths = _collect_child_refs(memory_dir, session_id)
        child_refs = refs
        if child_summaries:
            body_parts.append("## Subagent children\n\n" + "\n".join(child_summaries))

    buffer_files = list((memory_dir / "_buffer").glob("*.md")) if (memory_dir / "_buffer").exists() else []
    episode: dict[str, Any] = {
        "session_id": session_id,
        "hook": hook_event,
        "event_id": event_id,
        "turn": len(buffer_files) + 1,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "kind": kind,
        "summary": "\n\n".join(body_parts),
    }
    theme = _theme_from(user_text)
    if theme:
        episode["theme"] = theme
    if parent_session_id:
        episode["parent_session_id"] = parent_session_id
    if child_refs:
        episode["child_refs"] = child_refs

    append_buffer_turn(memory_dir, episode)
    # After the parent Stop is persisted, mark any consumed subagent children
    # so later Stops in this same session don't re-fold the same children.
    if child_paths:
        mark_consumed(memory_dir, child_paths, event_id)
    return 0


def safe_main() -> int:
    """Top-level wrapper. Any exception becomes a dead-letter entry, not a silent drop."""
    raw = ""
    payload: dict[str, Any] = {}
    try:
        raw = sys.stdin.read()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        # Hand raw payload back to main() via a fresh stdin stream
        sys.stdin = io.StringIO(raw)
        return main()
    except BaseException as exc:  # noqa: BLE001
        try:
            cwd = Path(payload.get("cwd") or os.getcwd())
            memory_dir = cwd / ".memory"
            if memory_dir.exists():
                append_hook_error(
                    memory_dir=memory_dir,
                    payload=payload,
                    exc=exc,
                    hook_name=payload.get("hook_event_name", "Stop"),
                )
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    raise SystemExit(safe_main())
