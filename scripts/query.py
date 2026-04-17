"""Query CLI: ask questions against the knowledge/ articles.

Full-context approach (Karpathy): for small KBs (<500 articles), stuffing
the entire index plus article bodies into the prompt beats RAG on accuracy
and needs zero infrastructure. Above SIZE_WARN_BYTES we trim to index + top-N.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

import llm  # noqa: E402

SIZE_WARN_BYTES = 50_000
TOP_N_ON_OVERFLOW = 20

QUERY_SYSTEM_PROMPT = """너는 사용자의 개인 지식 베이스를 읽고 질문에 답하는 어시스턴트다.
제공된 knowledge/index.md와 concept/connection 아티클만을 근거로 답하라.
아티클에 없는 내용이면 모른다고 말하고, 답변에 근거가 되는 concept id를 [[id]] 형식으로 인용하라.
"""


def _collect_articles(knowledge_dir: Path) -> tuple[str, list[Path]]:
    index_path = knowledge_dir / "index.md"
    index_text = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    article_paths: list[Path] = []
    for sub in ("concepts", "connections"):
        d = knowledge_dir / sub
        if d.exists():
            article_paths.extend(sorted(d.glob("*.md")))
    return index_text, article_paths


def _assemble_context(index_text: str, articles: list[Path]) -> tuple[str, bool]:
    full_body = "\n\n".join(
        f"## {p.relative_to(p.parent.parent)}\n\n{p.read_text(encoding='utf-8')}"
        for p in articles
    )
    full = f"# index.md\n\n{index_text}\n\n# Articles\n\n{full_body}"
    if len(full.encode("utf-8")) <= SIZE_WARN_BYTES:
        return full, False

    trimmed_articles = articles[:TOP_N_ON_OVERFLOW]
    trimmed_body = "\n\n".join(
        f"## {p.relative_to(p.parent.parent)}\n\n{p.read_text(encoding='utf-8')}"
        for p in trimmed_articles
    )
    trimmed = (
        f"# index.md\n\n{index_text}\n\n"
        f"# Articles (first {len(trimmed_articles)} of {len(articles)}, trimmed by size)\n\n{trimmed_body}"
    )
    return trimmed, True


def run_query(memory_dir: Path, question: str) -> str:
    memory_dir = Path(memory_dir)
    knowledge_dir = memory_dir / "knowledge"
    if not knowledge_dir.exists():
        return "No knowledge/ directory found. Run a session with ANTHROPIC_API_KEY set first."

    if not llm.is_available():
        return (
            "LLM unavailable. Ensure `anthropic` is installed and ANTHROPIC_API_KEY is set, "
            "and that CLAUDE_INVOKED_BY is not 'memory-compiler'."
        )

    index_text, articles = _collect_articles(knowledge_dir)
    if not articles and not index_text.strip():
        return "Knowledge base is empty. Run some sessions first so compile.py can populate it."

    context, trimmed = _assemble_context(index_text, articles)
    if trimmed:
        sys.stderr.write(
            f"[query] KB exceeded {SIZE_WARN_BYTES} bytes; trimmed to first {TOP_N_ON_OVERFLOW} articles.\n"
        )

    user_prompt = f"{context}\n\n# Question\n\n{question}"
    response = llm.call(QUERY_SYSTEM_PROMPT, user_prompt, max_tokens=2048)
    return response or "(LLM returned no answer.)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="query", description="Query the .memory/ knowledge base.")
    parser.add_argument("memory_dir", type=Path, help="Path to the .memory/ directory")
    parser.add_argument("question", type=str, help="Natural language question")
    args = parser.parse_args(argv)

    answer = run_query(args.memory_dir, args.question)
    sys.stdout.write(answer + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
