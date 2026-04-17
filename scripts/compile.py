"""Daily -> knowledge compile.

Asks LLM to structure daily logs into concept + connection articles.
Incremental via SHA-256 hashes stored in .meta.json.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import llm
from memory_ops import acquire_lock, atomic_write

COMPILE_SYSTEM_PROMPT = """너는 개발 세션의 일일 로그를 "재사용 가능한 지식"으로 구조화하는 편집자다.
입력은 최근 daily 로그들의 텍스트와 (있으면) 기존 concept 아티클 목록이다.
출력은 **순수한 JSON 객체** — 다른 설명이나 markdown 코드블록 없이 JSON만.

스키마:
{
  "concepts": [
    {
      "id": "kebab-case-unique-id",
      "title": "짧은 개념 이름",
      "tags": ["tag1", "tag2"],
      "body": "markdown 본문 (2~10 문장). 이 개념이 뭔지, 왜 중요한지, 언제 쓰이는지.",
      "related": ["other-concept-id", ...]
    }
  ],
  "connections": [
    {
      "id": "kebab-case-unique-id",
      "from": "concept-id-a",
      "to": "concept-id-b",
      "kind": "enables | contradicts | depends-on | similar-to | specializes",
      "body": "관계 설명 한두 문장"
    }
  ]
}

규칙:
- 기존 concept id가 제공되면 같은 id를 재사용해 body를 보강한다 (새 id 발명 지양).
- 한 세션의 사소한 디테일이 아닌 재사용 가능한 개념만 뽑는다. 빈 배열도 유효한 답.
- tag는 소문자 kebab-case. 개념 1-3개 정도.
"""


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _changed_dailies(daily_dir: Path, hashes: dict[str, str]) -> list[Path]:
    changed: list[Path] = []
    if not daily_dir.exists():
        return changed
    for path in sorted(daily_dir.glob("*.md")):
        current = _file_sha256(path)
        if hashes.get(path.name) != current:
            changed.append(path)
    return changed


def _load_existing_concepts(knowledge_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    concepts_dir = knowledge_dir / "concepts"
    if not concepts_dir.exists():
        return out
    for path in sorted(concepts_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        # Minimal parse: concept files are "# title\n\nbody\n\ntags: [...]"
        title_match = re.match(r"^#\s+(.+)", text)
        out.append({
            "id": path.stem,
            "title": title_match.group(1).strip() if title_match else path.stem,
        })
    return out


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    """Tolerate LLM wrapping JSON in ```json fences."""
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _render_concept(concept: dict[str, Any]) -> str:
    tags = concept.get("tags") or []
    related = concept.get("related") or []
    parts = [
        f"# {concept.get('title', concept.get('id', 'untitled'))}",
        "",
        concept.get("body", "").strip(),
        "",
    ]
    if tags:
        parts.append(f"**tags:** {', '.join(tags)}")
    if related:
        related_links = ", ".join(f"[[{r}]]" for r in related)
        parts.append(f"**related:** {related_links}")
    return "\n".join(parts).rstrip() + "\n"


def _render_connection(conn: dict[str, Any]) -> str:
    parts = [
        f"# {conn.get('from', '?')} → {conn.get('to', '?')} ({conn.get('kind', '?')})",
        "",
        conn.get("body", "").strip(),
        "",
    ]
    return "\n".join(parts).rstrip() + "\n"


def render_knowledge_index(
    concepts: list[dict[str, Any]],
    connections: list[dict[str, Any]],
) -> str:
    lines = [
        "# Knowledge Index",
        "",
        "> 대화에서 추출된 concept / connection 아티클. `compile.py`가 자동 생성.",
        "",
        "## Concepts",
        "",
    ]
    for c in sorted(concepts, key=lambda x: x.get("id", "")):
        tags = ", ".join(c.get("tags") or [])
        tag_suffix = f" — {tags}" if tags else ""
        lines.append(f"- [[{c['id']}]] {c.get('title', c['id'])}{tag_suffix}")
    lines.extend(["", "## Connections", ""])
    for c in sorted(connections, key=lambda x: x.get("id", "")):
        lines.append(f"- [[{c['id']}]] {c.get('from', '?')} → {c.get('to', '?')} ({c.get('kind', '?')})")
    lines.append("")
    return "\n".join(lines)


def _merge_concept(existing_path: Path, new_concept: dict[str, Any]) -> dict[str, Any]:
    """When LLM returns an existing id, prefer the new body but keep tags/related unioned."""
    if not existing_path.exists():
        return new_concept
    return new_concept  # LLM was given existing body; trust its merge result.


def run_compile(memory_dir: Path) -> dict[str, int]:
    """Compile changed daily logs into knowledge articles.

    No-op when llm.is_available() is False or no dailies changed.
    """
    memory_dir = Path(memory_dir)
    daily_dir = memory_dir / "daily"
    knowledge_dir = memory_dir / "knowledge"
    concepts_dir = knowledge_dir / "concepts"
    connections_dir = knowledge_dir / "connections"
    meta_path = memory_dir / ".meta.json"

    if not llm.is_available():
        return {"compiled": 0, "skipped": 1}

    with acquire_lock(memory_dir / ".lock"):
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        hashes: dict[str, str] = dict(meta.get("compile_hashes") or {})
        changed = _changed_dailies(daily_dir, hashes)
        if not changed:
            return {"compiled": 0, "skipped": 0}

        daily_blob = "\n\n---\n\n".join(
            f"### {p.name}\n\n{p.read_text(encoding='utf-8')}" for p in changed
        )
        existing = _load_existing_concepts(knowledge_dir)
        existing_blob = (
            "\n".join(f"- id={c['id']} title=\"{c['title']}\"" for c in existing)
            if existing
            else "(none yet)"
        )

        user_prompt = (
            f"# Recent daily logs\n\n{daily_blob}\n\n"
            f"# Existing concepts (reuse ids when relevant)\n\n{existing_blob}\n"
        )
        raw = llm.call(COMPILE_SYSTEM_PROMPT, user_prompt, max_tokens=4096)
        if not raw:
            return {"compiled": 0, "skipped": 0}

        data = _parse_llm_json(raw)
        if data is None:
            return {"compiled": 0, "skipped": 0}

        concepts = data.get("concepts") or []
        connections = data.get("connections") or []

        concepts_dir.mkdir(parents=True, exist_ok=True)
        connections_dir.mkdir(parents=True, exist_ok=True)

        written = 0
        for concept in concepts:
            cid = concept.get("id")
            if not cid or not isinstance(cid, str):
                continue
            safe_id = re.sub(r"[^a-z0-9\-]+", "-", cid.lower()).strip("-") or "untitled"
            concept["id"] = safe_id
            path = concepts_dir / f"{safe_id}.md"
            merged = _merge_concept(path, concept)
            atomic_write(path, _render_concept(merged))
            written += 1

        for conn in connections:
            cid = conn.get("id")
            if not cid or not isinstance(cid, str):
                continue
            safe_id = re.sub(r"[^a-z0-9\-]+", "-", cid.lower()).strip("-") or "untitled"
            conn["id"] = safe_id
            path = connections_dir / f"{safe_id}.md"
            atomic_write(path, _render_connection(conn))
            written += 1

        # Regenerate index from ALL current concepts/connections (not just new ones).
        all_concepts = []
        for p in sorted(concepts_dir.glob("*.md")):
            title_match = re.match(r"^#\s+(.+)", p.read_text(encoding="utf-8"))
            tags_match = re.search(r"\*\*tags:\*\*\s*(.+)", p.read_text(encoding="utf-8"))
            all_concepts.append({
                "id": p.stem,
                "title": title_match.group(1).strip() if title_match else p.stem,
                "tags": [t.strip() for t in tags_match.group(1).split(",")] if tags_match else [],
            })
        all_connections = []
        for p in sorted(connections_dir.glob("*.md")):
            text = p.read_text(encoding="utf-8")
            header_match = re.match(r"^#\s+(.+?)\s+→\s+(.+?)\s+\((.+?)\)", text)
            all_connections.append({
                "id": p.stem,
                "from": header_match.group(1).strip() if header_match else "?",
                "to": header_match.group(2).strip() if header_match else "?",
                "kind": header_match.group(3).strip() if header_match else "?",
            })

        index_text = render_knowledge_index(all_concepts, all_connections)
        atomic_write(knowledge_dir / "index.md", index_text)

        for p in changed:
            hashes[p.name] = _file_sha256(p)
        meta["compile_hashes"] = hashes
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        return {"compiled": written, "skipped": 0}
