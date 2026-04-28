"""Consolidation pipeline: buffer -> long-term memory.

Pure logic. File access happens through memory_ops.
"""
from __future__ import annotations

import datetime
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import yaml

from memory_ops import (
    _write_entry_locked,
    acquire_lock,
    atomic_write,
    parse_buffer_file,
    parse_memory_index,
    render_memory_index,
)


def similarity(a: str, b: str) -> float:
    """Quick similarity score in [0, 1].

    Hybrid of character-level SequenceMatcher and token Jaccard:
    - Near-duplicates (shared tokens OR high char ratio) score high.
    - Unrelated English strings that happen to share common letters are
      penalized via the zero-token-overlap gate; this keeps things
      dependency-free while avoiding SequenceMatcher's letter-soup false
      positives on short English phrases.
    Good enough for near-duplicate detection; YAGNI for semantic upgrades.
    """
    if not a or not b:
        return 0.0
    char_ratio = SequenceMatcher(None, a, b).ratio()
    tokens_a = set(a.lower().split())
    tokens_b = set(b.lower().split())
    if tokens_a and tokens_b:
        intersection = len(tokens_a & tokens_b)
        union = len(tokens_a | tokens_b)
        token_ratio = intersection / union if union else 0.0
        if intersection == 0:
            # No shared tokens: cap at half of char ratio so unrelated
            # strings with incidental letter overlap stay clearly low.
            return char_ratio * 0.5
        return max(char_ratio, token_ratio)
    return char_ratio


def find_duplicates(
    entries: list[dict[str, Any]], threshold: float = 0.8
) -> list[tuple[str, str]]:
    """Return pairs of entry ids whose summaries exceed the similarity threshold.

    Pairs are unordered; each pair appears once.
    """
    pairs: list[tuple[str, str]] = []
    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            sim = similarity(entries[i].get("summary", ""), entries[j].get("summary", ""))
            if sim >= threshold:
                pairs.append((entries[i]["id"], entries[j]["id"]))
    return pairs


def detect_promotions(buffer_episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return pattern promotion candidates: themes seen in 2+ independent sessions.

    Independent = different session_id. Same session repeats count as 1.
    Returns one dict per promoted theme with evidence_count and sample summary.
    """
    by_theme: dict[str, dict[str, Any]] = {}
    for ep in buffer_episodes:
        theme = ep.get("theme")
        if not theme:
            continue
        slot = by_theme.setdefault(theme, {"sessions": set(), "samples": []})
        slot["sessions"].add(ep.get("session_id", "unknown"))
        slot["samples"].append(ep.get("summary", ""))

    promotions: list[dict[str, Any]] = []
    for theme, data in by_theme.items():
        session_count = len(data["sessions"])
        if session_count >= 2:
            promotions.append(
                {
                    "theme": theme,
                    "evidence_count": session_count,
                    "sample_summary": data["samples"][0],
                }
            )
    return promotions


def _read_buffer_episodes(
    memory_dir: Path, sentinel_name: str = ".consolidated"
) -> list[dict[str, Any]]:
    """Read all unprocessed turn files from _buffer/.

    sentinel_name lets callers (consolidate vs flush) advance independently —
    both scan the same buffer but track their own progress marker.
    """
    buffer_dir = memory_dir / "_buffer"
    if not buffer_dir.exists():
        return []

    sentinel = buffer_dir / sentinel_name
    cutoff = sentinel.stat().st_mtime if sentinel.exists() else 0.0

    # Accept both legacy ``session-<sid>-turn-NNNN.md`` and v2
    # ``<ts_ns>-<sid>-<hook>-<hash>.md`` filenames. Hook name appears
    # untruncated in v2 filenames, so the pattern must match each event kind.
    buffer_globs = (
        "session-*.md",
        "*-Stop-*.md",
        "*-StopFailure-*.md",
        "*-SubagentStop-*.md",
        "*-PreCompact-*.md",
    )
    candidates = {p for pattern in buffer_globs for p in buffer_dir.glob(pattern)}

    episodes: list[dict[str, Any]] = []
    for path in sorted(candidates):
        if path.name.startswith("."):
            continue
        if path.stat().st_mtime <= cutoff:
            continue
        parsed = parse_buffer_file(path)
        if parsed is None:
            continue
        fm, body = parsed
        episode = dict(fm)
        episode["summary"] = body or fm.get("summary", "")
        episodes.append(episode)
    return episodes


def _cleanup_old_buffer_files(
    buffer_dir: Path, sentinel: Path, max_age_days: int = 30
) -> int:
    """Remove already-processed buffer files older than max_age_days."""
    if not sentinel.exists():
        return 0
    cutoff_mtime = sentinel.stat().st_mtime
    age_cutoff = datetime.datetime.now().timestamp() - max_age_days * 86400
    removed = 0
    for path in list(buffer_dir.glob("*.md")):
        if path.name.startswith("."):
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime <= cutoff_mtime and st.st_mtime < age_cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _update_meta_json(memory_dir: Path) -> None:
    """Update .meta.json with current consolidation timestamp."""
    meta_path = memory_dir / ".meta.json"
    if not meta_path.exists():
        return
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        data["last_consolidated"] = datetime.datetime.now().isoformat(timespec="seconds")
        atomic_write(meta_path, json.dumps(data, indent=2))
    except (json.JSONDecodeError, OSError):
        pass


def run_consolidation(memory_dir: Path) -> dict[str, int]:
    """Execute full consolidation pass on a .memory/ directory.

    Reads _buffer/, detects promotions/duplicates, writes updates, advances sentinel.
    Returns counters for the caller to log.

    Thread/process safe: uses an exclusive file lock so concurrent sessions
    don't race on buffer reads or MEMORY.md writes. Uses _write_entry_locked
    internally so we don't re-enter the same-process lock.
    """
    memory_dir = Path(memory_dir)
    buffer_dir = memory_dir / "_buffer"
    buffer_dir.mkdir(exist_ok=True)

    with acquire_lock(memory_dir / ".lock"):
        episodes = _read_buffer_episodes(memory_dir)
        promoted = 0
        duplicates_found = 0
        duplicate_notes: list[str] = []

        if episodes:
            promotions = detect_promotions(episodes)
            today = datetime.date.today().isoformat()
            for p in promotions:
                theme = p["theme"]
                entry = {
                    "id": f"pat.{theme}",
                    "type": "pattern",
                    "summary": p["sample_summary"][:80],
                    "scope": "local",
                    "updated": today,
                    "confidence": "medium",
                    "tags": [theme.split("-")[0] if "-" in theme else theme],
                    "path": f"patterns/{theme}.md",
                    "evidence_count": p["evidence_count"],
                }
                body = f"반복 관찰된 pattern. evidence_count={p['evidence_count']}"
                _write_entry_locked(memory_dir, entry, body)
                promoted += 1

            current = parse_memory_index(memory_dir / "MEMORY.md")
            for section_name, section_entries in current.items():
                dupes = find_duplicates(section_entries, threshold=0.85)
                duplicates_found += len(dupes)
                for id_a, id_b in dupes:
                    duplicate_notes.append(
                        f"- {section_name}: `{id_a}` ↔ `{id_b}` (유사도 높음, 수동 정리 권장)"
                    )

            if duplicate_notes:
                rendered = render_memory_index(
                    current, promotion_candidates=duplicate_notes
                )
                atomic_write(memory_dir / "MEMORY.md", rendered)

        sentinel = buffer_dir / ".consolidated"
        _cleanup_old_buffer_files(buffer_dir, sentinel)
        sentinel.touch()
        _update_meta_json(memory_dir)

        return {
            "promoted": promoted,
            "duplicates_found": duplicates_found,
            "episodes_seen": len(episodes),
        }
