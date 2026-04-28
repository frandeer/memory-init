---
name: memory-init
description: "프로젝트별 영구 메모리 시스템을 부트스트랩한다. 'memory init', '/memory-init', '메모리 세팅', '메모리 시스템 만들어줘', '이 프로젝트 메모리 시작' 같은 요청 시 사용. 최초 1회 글로벌 훅을 설치하고 매 프로젝트에서 .memory/ 디렉토리를 초기화한다."
---

# memory-init — 영구 메모리 시스템 부트스트랩

프로젝트 루트의 `.memory/`에 대화 턴과 장기 규칙을 적재한다. LLM 의존 없음,
훅 실패는 dead-letter 로그로 가시화, 동시성은 파일 락으로 직렬화.

## 동작

1. **글로벌 부트스트랩 (최초 1회)**
   - `~/.claude/settings.json`에 5개 훅 등록: SessionStart / Stop / StopFailure / SubagentStop / PreCompact
   - 훅은 현재 디렉토리에 `.memory/`가 있을 때만 동작 (없으면 no-op)
   - 재실행 idempotent — 중복 등록 없음

2. **프로젝트 초기화 (매번)**
   - `.memory/` 생성: `MEMORY.md`, `STATE.md`, `TASKS.md`, `.meta.json`, `rules/`, `lessons/`, `patterns/`, `_buffer/`
   - 기존 `.memory/`가 있으면 건드리지 않음
   - `daily/`, `_archive/`, `knowledge/`가 남아 있으면 `_migrated-YYYYMMDD/`로 이동해 데이터 보존 (구버전 마이그레이션)
   - `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml` 등을 읽어 기술 스택 태그 자동 감지

## 실행 방법

```bash
# 최초 1회 — 글로벌 훅 설치
python ~/.claude/skills/memory-init/scripts/bootstrap.py install-global

# 매 프로젝트에서 — .memory/ 초기화
python ~/.claude/skills/memory-init/scripts/bootstrap.py init-project <project_root>
```

## 런타임 흐름

```
Stop / SubagentStop / PreCompact  →  stop.py  →  .memory/_buffer/<event>.md
StopFailure                        ↗
                                              ↓  (safe_main wrapper)
                                    예외 발생 시 _hook_errors.jsonl에 dead-letter

SessionStart  →  session_start.py  →  run_consolidation(_buffer) → patterns/
                                    →  MEMORY.md 갱신
                                    →  최근 _hook_errors 요약 주입
```

**파일명 스킴 (v2)**: `<ts_ns>-<sid>-<hook>-<hash>.md` — timestamp_ns + 8자 event_hash로 동시 firing에도 충돌 없음. `turn` 필드는 정렬용 메타데이터만.

**본문 구성**: user 텍스트 + assistant 텍스트(8KB head+tail 절단) + Tools 섹션(Edit의 file_path, Bash의 command, exit 상태만 — excerpt 저장 안 함).

**Subagent hybrid**: SubagentStop → `kind: subagent_turn` 별도 파일. 부모 Stop은 같은 session_id의 child 작업을 찾아 frontmatter `child_refs`와 본문 요약으로 임베드.

## 주의

- Claude Code 기본 auto-memory(`~/.claude/projects/<slug>/memory/`)와 **동시 사용하지 마세요**. `install-global`이 `~/.claude/CLAUDE.md`에 override 섹션을 자동 추가합니다.
- LLM 파이프라인(daily/knowledge)은 제거됐습니다. `ANTHROPIC_API_KEY` 불필요.

## 파일 구조

- `scripts/bootstrap.py` — `install-global` / `init-project` CLI + 레거시 마이그레이션
- `scripts/memory_ops.py` — 파일 I/O, 락, `append_buffer_turn`, `append_hook_error`, `compute_event_id`
- `scripts/stop.py` — Stop/StopFailure/SubagentStop/PreCompact 공용 진입 (`safe_main`으로 감쌈)
- `scripts/pre_compact.py` — stop.safe_main 위임 래퍼
- `scripts/session_start.py` — consolidation + MEMORY.md/에러 요약 주입
- `scripts/consolidate.py` — buffer → rules/lessons/patterns 승격 (문자열 유사도, LLM 없음)
- `templates/` — 초기 MEMORY/STATE/TASKS 템플릿
- `tests/` — pytest 스위트
