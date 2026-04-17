#!/usr/bin/env python
"""SessionStart hook entry. Loads MEMORY.md and runs catch-up pipelines."""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

# Make sibling modules importable
sys.path.insert(0, str(Path(__file__).parent))

import llm  # noqa: E402
from consolidate import run_consolidation  # noqa: E402
from memory_ops import parse_memory_index  # noqa: E402


def main() -> int:
    # Recursion guard: if we triggered ourselves via the Agent SDK, do nothing.
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

    # 1. Rules/lessons/patterns consolidation (existing behavior)
    consolidation = run_consolidation(memory_dir)

    # 2. Knowledge layer: flush -> compile. Both no-op when LLM unavailable.
    try:
        import flush
        import compile as compile_mod

        flush.run_flush(memory_dir)
        compile_mod.run_compile(memory_dir)
    except Exception:
        # Knowledge layer is optional; any failure must not block SessionStart.
        pass

    # 3. Build context to inject
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

    knowledge_text = ""
    knowledge_index = memory_dir / "knowledge" / "index.md"
    if knowledge_index.exists():
        k_lines = knowledge_index.read_text(encoding="utf-8").splitlines()
        if len(k_lines) > 100:
            k_lines = k_lines[:100] + ["", "<!-- knowledge index truncated at 100 lines -->"]
        knowledge_text = "\n".join(k_lines)

    daily_text = ""
    today = datetime.date.today().isoformat()
    daily_path = memory_dir / "daily" / f"{today}.md"
    if daily_path.exists():
        d_lines = daily_path.read_text(encoding="utf-8").splitlines()
        tail = d_lines[-30:] if len(d_lines) > 30 else d_lines
        daily_text = "\n".join(tail)

    output_parts = [
        f"# Memory index (from {memory_dir})",
        "",
        index_text,
    ]
    if knowledge_text:
        output_parts.extend(["", "# Knowledge index", "", knowledge_text])
    if daily_text:
        output_parts.extend(["", f"# Today's daily log tail ({today})", "", daily_text])
    if state_text:
        output_parts.extend(["", "# Current STATE", "", state_text])
    if consolidation.get("promoted"):
        output_parts.append(f"\n<!-- consolidation: promoted={consolidation['promoted']} -->")

    sys.stdout.write("\n".join(output_parts) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
