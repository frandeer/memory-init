#!/usr/bin/env python
"""SessionStart hook entry. Loads MEMORY.md and runs catch-up consolidation."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Make sibling modules importable
sys.path.insert(0, str(Path(__file__).parent))

from consolidate import run_consolidation  # noqa: E402
from memory_ops import parse_memory_index  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}

    cwd = Path(payload.get("cwd") or os.getcwd())
    memory_dir = cwd / ".memory"
    if not memory_dir.exists():
        return 0

    # 1. Catch-up consolidation if buffer has unprocessed entries
    result = run_consolidation(memory_dir)

    # 2. Build context to inject
    index_path = memory_dir / "MEMORY.md"
    if not index_path.exists():
        return 0
    index_text = index_path.read_text(encoding="utf-8")

    # Respect the <=150 line hard cap
    lines = index_text.splitlines()
    if len(lines) > 150:
        index_text = "\n".join(lines[:150]) + "\n\n<!-- truncated at 150 lines -->"

    # Optionally inject STATE.md body on resume/compact
    source = payload.get("source", "startup")
    state_text = ""
    if source in {"resume", "compact"}:
        state_path = memory_dir / "STATE.md"
        if state_path.exists():
            state_text = state_path.read_text(encoding="utf-8")

    # Emit text to stdout — it will be appended to the system prompt context.
    output_parts = [
        f"# Memory index (from {memory_dir})",
        "",
        index_text,
    ]
    if state_text:
        output_parts.extend(["", "# Current STATE", "", state_text])
    if result.get("promoted"):
        output_parts.append(f"\n<!-- consolidation: promoted={result['promoted']} -->")

    sys.stdout.write("\n".join(output_parts) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
