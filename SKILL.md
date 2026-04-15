---
name: memory-init
description: "프로젝트별 영구 메모리 시스템을 부트스트랩한다. 'memory init', '/memory-init', '메모리 세팅', '메모리 시스템 만들어줘', '이 프로젝트 메모리 시작' 같은 요청 시 사용. 최초 1회 글로벌 훅을 설치하고 매 프로젝트에서 .memory/ 디렉토리를 초기화한다."
---

# memory-init — 영구 메모리 시스템 부트스트랩

이 스킬은 "경험이 쌓이는 방식"으로 자동 축적·최적화·전파되는 범용 메모리 시스템을 현재 프로젝트에 설치한다.

## 동작

1. **글로벌 부트스트랩 (최초 1회)**
   - `~/.claude/settings.json`에 SessionStart + Stop + StopFailure 훅 등록
   - 훅은 **현재 디렉토리에 `.memory/`가 있을 때만 동작**, 없으면 no-op fallback
   - 이미 설치돼 있으면 skip

2. **프로젝트 초기화 (매번)**
   - 현재 디렉토리에 `.memory/` 구조 생성: `MEMORY.md`, `STATE.md`, `TASKS.md`, `.meta.json`, `rules/`, `lessons/`, `patterns/`, `_buffer/`, `_archive/`
   - 기존에 `.memory/`가 있으면 건드리지 않음 (idempotent)
   - `package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `requirements.txt` 중 있는 것을 읽어 기술 스택 태그 자동 감지 → `.meta.json`의 `project_tags`에 저장

3. **사용자에게 질문 1개**
   - *"이 프로젝트에서 특히 조심할 부분이 있나요? (예: 특정 라이브러리의 함정, 팀 규칙, 자주 하는 실수)"*
   - 사용자가 답하면 첫 lesson 파일 생성
   - "없음" 또는 건너뛰면 빈 구조만

## 실행 방법

Claude가 이 스킬을 호출할 때:

```bash
# 최초 1회 — 글로벌 훅 설치
python ~/.claude/skills/memory-init/scripts/bootstrap.py install-global

# 매 프로젝트에서 — .memory/ 초기화
python ~/.claude/skills/memory-init/scripts/bootstrap.py init-project <project_root>
```

## 주의

- Claude Code 기본 auto-memory(`~/.claude/projects/<project-slug>/memory/`)와 **동시 사용하지 마세요**. 이 시스템을 쓰기로 결정하면 `~/.claude/CLAUDE.md`에 "이 시스템 사용, 기본 auto-memory 비활성화" 섹션을 수동으로 추가해야 합니다.
- `D:/lab/document` 같은 기존 auto-memory 파일이 있는 프로젝트는 수동 마이그레이션이 필요합니다.

## 파일 구조

- `scripts/bootstrap.py` — 진입점 (init-project, install-global)
- `scripts/memory_ops.py` — 파일 I/O 유틸
- `scripts/consolidate.py` — consolidation 파이프라인 (similarity, find_duplicates, detect_promotions, run_consolidation)
- `scripts/session_start.py` — SessionStart 훅 어댑터
- `scripts/stop.py` — Stop/StopFailure 훅 어댑터
- `templates/` — 초기 MEMORY/STATE/TASKS 템플릿

## 스펙

전체 설계 문서: `D:/lab/document/docs/superpowers/specs/2026-04-15-memory-system-design.md`
구현 계획: `D:/lab/document/docs/superpowers/plans/2026-04-15-memory-system.md`
