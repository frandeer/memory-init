"""Buffer -> daily flush.

Reads unprocessed _buffer/ episodes and asks an LLM to extract the real
signals (decisions, new learnings, blockers) into a daily markdown log.
Skipped silently when llm.is_available() is False.
"""
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import llm
from consolidate import _read_buffer_episodes
from memory_ops import acquire_lock, atomic_write

SKILL_ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = SKILL_ROOT / "templates"

FLUSH_SYSTEM_PROMPT = """너는 개발 대화 로그에서 "기억할 가치가 있는 신호"만 뽑아내는 추출기다.
입력은 한 세션의 턴별 요약이다. 출력은 markdown bullet list로, 각 항목은 다음 셋 중 하나:
- **decision**: 중요한 설계/방향 결정
- **learning**: 처음 알게 된 사실이나 개념
- **blocker**: 막혔거나 미해결인 지점

잡담, 반복, 단순 tool 호출, 의미 없는 요약은 **완전히 버려라**. 실제 지식이 없으면 빈 출력을 반환하라.
각 bullet은 한 줄, 주어/동사/객체가 명확해야 한다. 세션 ID나 턴 번호는 넣지 말 것.
"""


def _format_episodes_for_llm(episodes: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for ep in episodes:
        theme = ep.get("theme", "")
        tag = f" [#{theme}]" if theme else ""
        lines.append(f"- turn {ep.get('turn', '?')}{tag}: {ep.get('summary', '').strip()}")
    return "\n".join(lines)


def _append_to_daily(daily_path: Path, session_id: str, extracted: str) -> None:
    """Append a section to today's daily file, creating it with the template if missing."""
    today = datetime.date.today().isoformat()
    if daily_path.exists():
        existing = daily_path.read_text(encoding="utf-8")
    else:
        tmpl = (TEMPLATES_DIR / "daily.md.tmpl").read_text(encoding="utf-8")
        existing = tmpl.format(date=today)

    block = f"\n## Session {session_id} — {datetime.datetime.now().isoformat(timespec='seconds')}\n\n{extracted.strip()}\n"
    atomic_write(daily_path, existing + block)


def _mark_flushed(buffer_dir: Path) -> None:
    (buffer_dir / ".flushed").touch()


def run_flush(memory_dir: Path) -> dict[str, int]:
    """Flush new _buffer/ episodes to daily/YYYY-MM-DD.md via LLM extraction.

    Returns counters. Silently no-ops when LLM unavailable — the episodes stay
    in the buffer for a future session where LLM access is restored.
    """
    memory_dir = Path(memory_dir)
    buffer_dir = memory_dir / "_buffer"
    daily_dir = memory_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    if not llm.is_available():
        return {"episodes_seen": 0, "flushed": 0, "skipped": 1}

    with acquire_lock(memory_dir / ".lock"):
        episodes = _read_buffer_episodes(memory_dir, sentinel_name=".flushed")
        if not episodes:
            return {"episodes_seen": 0, "flushed": 0, "skipped": 0}

        by_session: dict[str, list[dict[str, Any]]] = {}
        for ep in episodes:
            sid = ep.get("session_id") or "unknown"
            by_session.setdefault(sid, []).append(ep)

        today = datetime.date.today().isoformat()
        daily_path = daily_dir / f"{today}.md"
        flushed_sessions = 0

        for sid, eps in by_session.items():
            user_prompt = _format_episodes_for_llm(eps)
            extracted = llm.call(FLUSH_SYSTEM_PROMPT, user_prompt)
            if not extracted:
                continue
            _append_to_daily(daily_path, sid, extracted)
            flushed_sessions += 1

        _mark_flushed(buffer_dir)
        return {
            "episodes_seen": len(episodes),
            "flushed": flushed_sessions,
            "skipped": 0,
        }
