"""Consolidation pipeline: buffer -> long-term memory.

Pure logic. File access happens through memory_ops.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


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
