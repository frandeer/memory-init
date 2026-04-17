"""Tests for compile.py — LLM mocked."""
import json

import pytest

import compile as compile_mod
import llm


def _seed_daily(memory_dir, name, body):
    daily_dir = memory_dir / "daily"
    daily_dir.mkdir(exist_ok=True)
    (daily_dir / name).write_text(body, encoding="utf-8")


def _init_meta(memory_dir, hashes=None):
    meta = {"created": "2026-04-17", "compile_hashes": hashes or {}}
    (memory_dir / ".meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_compile_skips_when_llm_unavailable(tmp_memory_dir, monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: False)
    _init_meta(tmp_memory_dir)
    _seed_daily(tmp_memory_dir, "2026-04-17.md", "# day\n- decision: X\n")
    result = compile_mod.run_compile(tmp_memory_dir)
    assert result["skipped"] == 1
    assert not any((tmp_memory_dir / "knowledge" / "concepts").glob("*.md"))


def test_compile_writes_concepts_and_index(tmp_memory_dir, monkeypatch):
    monkeypatch.setattr(llm, "is_available", lambda: True)
    fake_response = json.dumps(
        {
            "concepts": [
                {
                    "id": "flush-pipeline",
                    "title": "Flush Pipeline",
                    "tags": ["memory", "llm"],
                    "body": "Extracts highlights from buffer into daily logs.",
                    "related": [],
                }
            ],
            "connections": [
                {
                    "id": "flush-depends-on-llm",
                    "from": "flush-pipeline",
                    "to": "llm-guard",
                    "kind": "depends-on",
                    "body": "Flush silently skips when LLM unavailable.",
                }
            ],
        }
    )
    monkeypatch.setattr(llm, "call", lambda *a, **k: fake_response)

    _init_meta(tmp_memory_dir)
    _seed_daily(tmp_memory_dir, "2026-04-17.md", "- decision: ship flush pipeline")

    result = compile_mod.run_compile(tmp_memory_dir)
    assert result["compiled"] == 2  # one concept + one connection

    concept = tmp_memory_dir / "knowledge" / "concepts" / "flush-pipeline.md"
    assert concept.exists()
    assert "Flush Pipeline" in concept.read_text(encoding="utf-8")

    conn = tmp_memory_dir / "knowledge" / "connections" / "flush-depends-on-llm.md"
    assert conn.exists()

    index = (tmp_memory_dir / "knowledge" / "index.md").read_text(encoding="utf-8")
    assert "flush-pipeline" in index
    assert "flush-depends-on-llm" in index


def test_compile_incremental_unchanged_daily_skipped(tmp_memory_dir, monkeypatch):
    """If a daily hasn't changed since last compile, LLM must not be called."""
    monkeypatch.setattr(llm, "is_available", lambda: True)
    call_count = {"n": 0}

    def counting_call(*a, **k):
        call_count["n"] += 1
        return json.dumps({"concepts": [], "connections": []})

    monkeypatch.setattr(llm, "call", counting_call)

    _init_meta(tmp_memory_dir)
    _seed_daily(tmp_memory_dir, "2026-04-17.md", "content v1")

    compile_mod.run_compile(tmp_memory_dir)  # first pass: hash gets recorded
    assert call_count["n"] == 1

    compile_mod.run_compile(tmp_memory_dir)  # no changes: LLM should NOT be called
    assert call_count["n"] == 1


def test_compile_handles_fenced_json(tmp_memory_dir, monkeypatch):
    """LLM wrapping JSON in ```json fences must still parse."""
    monkeypatch.setattr(llm, "is_available", lambda: True)
    fenced = "```json\n" + json.dumps({"concepts": [], "connections": []}) + "\n```"
    monkeypatch.setattr(llm, "call", lambda *a, **k: fenced)

    _init_meta(tmp_memory_dir)
    _seed_daily(tmp_memory_dir, "2026-04-17.md", "content")

    result = compile_mod.run_compile(tmp_memory_dir)
    assert result["compiled"] == 0  # empty but parsed successfully
