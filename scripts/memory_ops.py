"""File I/O utilities for the .memory/ system. Pure I/O, no business logic."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import time as _time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd) -> bool:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fd) -> None:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(fd) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    def _unlock(fd) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


@contextmanager
def acquire_lock(lock_path: Path, timeout: float = 5.0, poll_interval: float = 0.05):
    """Cross-process exclusive file lock.

    Blocks up to `timeout` seconds waiting for the lock. Raises TimeoutError
    on failure. The lock file is created if missing and kept on disk after
    release (for consistent state across runs).

    Usage:
        with acquire_lock(memory_dir / ".lock"):
            # critical section — read/modify/write files safely
            ...
    """
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Open in append+binary mode so the file is created if missing and we
    # can still lock the first byte via platform-specific APIs.
    fp = open(lock_path, "a+b")
    try:
        fp.seek(0)
        deadline = _time.monotonic() + timeout
        while not _try_lock(fp.fileno()):
            if _time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Could not acquire lock {lock_path} within {timeout}s"
                )
            _time.sleep(poll_interval)
        try:
            yield
        finally:
            fp.seek(0)
            _unlock(fp.fileno())
    finally:
        fp.close()


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


def _sanitize_for_filename(raw: str, max_len: int = 8) -> str:
    """Keep only filename-safe characters; truncate.

    Default max_len is 8 to keep session-id and event-hash segments short.
    Pass a larger max_len for hook names — truncating them breaks the glob
    patterns in consolidate._read_buffer_episodes (e.g. ``PreCompact`` would
    become ``PreCompa`` and never match ``*-PreCompact-*.md``).
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", raw or "")
    return cleaned[:max_len] or "unknown"


def append_buffer_turn(memory_dir: Path, episode: dict[str, Any]) -> Path:
    """Write one turn episode to ``_buffer/<ts_ns>-<sid>-<hook>-<hash>.md``.

    Thread/process safe: holds the per-memory-dir file lock while writing so
    concurrent Stop/SubagentStop hooks never collide on the same target. The
    filename is race-proof (timestamp + hash), so each Stop produces a unique
    entry even under concurrent firing.

    Idempotent: if ``episode["event_id"]`` matches an existing file, we skip
    the write. Callers compute event_id from transcript state.
    """
    memory_dir = Path(memory_dir)
    buffer_dir = memory_dir / "_buffer"
    buffer_dir.mkdir(exist_ok=True)

    session_id = str(episode.get("session_id", "unknown"))
    hook = str(episode.get("hook", "Stop"))
    event_id = str(episode.get("event_id") or "")
    turn = episode.get("turn", 0)

    # Filename identity = ts_ns + sid + hook + event_hash. turn is metadata.
    # Hook must NOT be truncated — consolidate._read_buffer_episodes matches
    # globs like ``*-PreCompact-*.md`` and ``*-StopFailure-*.md`` literally.
    ts_ns = _time.time_ns()
    sid_short = _sanitize_for_filename(session_id)
    hook_clean = _sanitize_for_filename(hook, max_len=32)
    hash_short = _sanitize_for_filename(event_id) or _sanitize_for_filename(str(ts_ns))
    filename = f"{ts_ns}-{sid_short}-{hook_clean}-{hash_short}.md"
    target = buffer_dir / filename

    with acquire_lock(memory_dir / ".lock", timeout=10):
        # Idempotency: same event_id already on disk? Bail out.
        if event_id:
            for existing in buffer_dir.glob(f"*-{hash_short}.md"):
                if existing.name.endswith(f"-{hash_short}.md"):
                    return existing
        if target.exists():
            return target

        frontmatter_dict: dict[str, Any] = {
            "schema": "memory-turn/v2",
            "session_id": session_id,
            "turn": turn,
            "timestamp": episode.get("timestamp", ""),
            "kind": episode.get("kind", "turn"),
            "hook": hook,
        }
        if event_id:
            frontmatter_dict["event_id"] = event_id
        if episode.get("parent_session_id"):
            frontmatter_dict["parent_session_id"] = episode["parent_session_id"]
        if episode.get("child_refs"):
            frontmatter_dict["child_refs"] = episode["child_refs"]
        if episode.get("theme"):
            frontmatter_dict["theme"] = episode["theme"]

        frontmatter = yaml.safe_dump(
            frontmatter_dict,
            allow_unicode=True,
            sort_keys=False,
        )
        body = episode.get("summary", "")
        content = f"---\n{frontmatter}---\n\n{body}\n"

        atomic_write(target, content)
    return target


def append_hook_error(
    memory_dir: Path,
    payload: dict[str, Any] | None,
    exc: BaseException,
    hook_name: str = "unknown",
) -> Path | None:
    """Append a dead-letter entry to ``_hook_errors.jsonl``.

    Safe to call from exception handlers: best-effort, swallows its own errors
    so a logging failure never breaks the calling hook.
    """
    try:
        memory_dir = Path(memory_dir)
        memory_dir.mkdir(parents=True, exist_ok=True)
        log_path = memory_dir / "_hook_errors.jsonl"
        safe_payload = {
            k: payload.get(k) if isinstance(payload, dict) else None
            for k in ("session_id", "cwd", "transcript_path", "hook_event_name")
        }
        entry = {
            "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
            "hook": hook_name,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "traceback_tail": "".join(traceback.format_exception(exc))[-1000:],
            **safe_payload,
        }
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return log_path
    except Exception:
        return None


_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n\n?(.*)$", re.DOTALL)


def parse_buffer_file(path: Path) -> tuple[dict[str, Any], str] | None:
    """Read a ``_buffer/*.md`` file and split it into frontmatter dict + body.

    Returns ``None`` if the file can't be read, doesn't match the frontmatter
    shape, or has invalid YAML. Used by both ``consolidate`` (buffer scanning)
    and ``stop`` (child_refs lookup).
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict):
        return None
    return fm, m.group(2).strip()


def mark_consumed(memory_dir: Path, paths: list[Path], parent_event_id: str) -> None:
    """Rewrite each ``_buffer/*.md`` path with ``consumed: <parent_event_id>`` in
    the frontmatter. Holds the memory-dir lock for the whole batch so child
    files can't be simultaneously consumed by two parent Stops.

    Safe to call with already-consumed paths (no-op on files that don't parse).
    """
    if not paths:
        return
    memory_dir = Path(memory_dir)
    with acquire_lock(memory_dir / ".lock", timeout=10):
        for path in paths:
            parsed = parse_buffer_file(path)
            if parsed is None:
                continue
            fm, body = parsed
            if fm.get("consumed"):
                continue
            fm["consumed"] = parent_event_id
            frontmatter = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
            atomic_write(path, f"---\n{frontmatter}---\n\n{body}\n")


def compute_event_id(
    session_id: str,
    hook: str,
    transcript_path: str | None,
    transcript_size: int,
    last_uuid: str | None,
) -> str:
    """Deterministic idempotency key for a hook firing."""
    payload = f"{session_id}|{hook}|{transcript_path or ''}|{transcript_size}|{last_uuid or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


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


def _write_entry_locked(memory_dir: Path, entry: dict[str, Any], body: str) -> None:
    """Internal helper: same as write_entry but does NOT acquire the lock.

    Caller must already hold ``acquire_lock(memory_dir / '.lock')``. This
    exists so run_consolidation (which takes the lock for its whole pass)
    can reuse the write logic without re-entering the lock from the same
    process — fcntl/msvcrt locks are per-FD and re-entry behaves badly.
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


def write_entry(memory_dir: Path, entry: dict[str, Any], body: str) -> None:
    """Write an entry file (rules/lessons/patterns) and update MEMORY.md.

    Idempotent: calling twice with the same id updates the existing entry.
    Thread/process safe: uses an exclusive file lock to prevent concurrent
    MEMORY.md corruption.
    """
    memory_dir = Path(memory_dir)
    with acquire_lock(memory_dir / ".lock"):
        _write_entry_locked(memory_dir, entry, body)
