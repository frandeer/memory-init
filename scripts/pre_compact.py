#!/usr/bin/env python
"""PreCompact hook.

Snapshots the current turn to ``_buffer/`` before auto-compaction trims the
transcript. Delegates to :mod:`stop.safe_main` so we share the same capture
logic (safe_main wrapper, tool-use metadata, dead-letter on error). ``stop``
branches on ``hook_event_name == "PreCompact"`` to tag the entry as
``kind: pre_compact``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from stop import safe_main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(safe_main())
