# memory-init — 다른 PC로 이식하는 방법

## 사전 요구사항

- **Claude Code** 설치됨
- **Python 3.9 이상** (`python --version`)
- **PyYAML**: `pip install pyyaml`

LLM/Anthropic 의존성은 **필요 없습니다** (파이프라인이 전부 파일 기반으로 재작성됨).

## 설치 절차

### 1. 스킬 디렉토리 배치

```bash
cd ~/.claude/skills
git clone https://github.com/frandeer/memory-init.git
```

수동 복사도 가능: 폴더를 `~/.claude/skills/memory-init/`에 배치.

### 2. Python 의존성

```bash
pip install pyyaml
```

### 3. 글로벌 부트스트랩

```bash
python ~/.claude/skills/memory-init/scripts/bootstrap.py install-global
```

수행 내용:
- `~/.claude/settings.json`에 5개 훅 등록: `SessionStart`, `Stop`, `StopFailure`, `SubagentStop`, `PreCompact`
- `~/.claude/CLAUDE.md`에 `<!-- memory-init: BEGIN/END -->` override 블록 추가

재실행 idempotent — 중복 등록 없음, 기존 블록은 최신 스니펫으로 교체.

### 4. 설치 검증 (선택)

```bash
cd ~/.claude/skills/memory-init
python -m pytest tests/ -v
```

모든 테스트가 passed로 나와야 정상.

### 5. 프로젝트 초기화

```bash
cd /path/to/project
python ~/.claude/skills/memory-init/scripts/bootstrap.py init-project .
```

생성되는 구조:
```
.memory/
├── MEMORY.md        # 규칙/교훈/패턴 인덱스
├── STATE.md         # 현재 작업 상태
├── TASKS.md         # 진행 중 작업
├── .meta.json       # 프로젝트 메타데이터
├── rules/           # 항상 지킬 규칙
├── lessons/         # 시행착오 교훈
├── patterns/        # 2+ 세션에서 반복 관찰된 패턴 (자동 승격)
├── _buffer/         # 턴별 에피소드 (미처리)
└── _hook_errors.jsonl  # 훅 실패 dead-letter (최초엔 없음)
```

구버전 설치(`daily/`, `_archive/`, `knowledge/` 존재)는 `init-project` 실행 시 자동으로 `_migrated-YYYYMMDD/`로 이동 — 데이터 손실 없음.

### 6. Claude Code 세션 시작

그 프로젝트 디렉토리에서 Claude Code를 실행하면 자동으로:
- **SessionStart** 훅이 `MEMORY.md` 인덱스 + 최근 훅 에러 요약을 컨텍스트에 주입
- **Stop / StopFailure / SubagentStop** 훅이 턴을 `_buffer/<ts_ns>-<sid>-<hook>-<hash>.md`로 기록
- **PreCompact** 훅이 auto-compaction 직전 스냅샷
- 모든 훅은 `safe_main()`으로 감싸져 있어 예외는 `_hook_errors.jsonl`에 기록되고 Claude 작업은 중단되지 않음

## 이식 시 주의

- `~/.claude/settings.json`과 `~/.claude/CLAUDE.md`는 PC마다 다르므로 **가져가지 마세요**. `install-global`이 target PC의 `$HOME`을 기반으로 안전하게 블록만 추가.
- 프로젝트별 `.memory/` 데이터는 프로젝트 디렉토리와 함께 동기화 (git/GDrive/Syncthing 등).

### Windows vs Unix

- 훅 커맨드는 `Path.as_posix()`로 forward slash 사용 — Windows Python + Git Bash 호환
- 파일 락은 플랫폼 자동 분기 (msvcrt / fcntl)

## 업데이트

```bash
cd ~/.claude/skills/memory-init
git pull
python -m pytest tests/ -v
python scripts/bootstrap.py install-global    # 훅/스니펫 최신화
```

## 제거

1. `~/.claude/CLAUDE.md`에서 `<!-- memory-init: BEGIN -->` ~ `END` 블록 삭제
2. `~/.claude/settings.json`에서 `SessionStart`/`Stop`/`StopFailure`/`SubagentStop`/`PreCompact` 중 `session_start.py` 또는 `stop.py`/`pre_compact.py`를 참조하는 항목 삭제
3. `~/.claude/skills/memory-init/` 삭제
4. 각 프로젝트의 `.memory/` 삭제 (데이터도 지울 때만)

## 현재 포함된 모듈

- `SKILL.md` — 스킬 정의
- `scripts/bootstrap.py` — `install-global` + `init-project` + 레거시 마이그레이션
- `scripts/memory_ops.py` — 파일 I/O, 크로스 플랫폼 락, `append_buffer_turn`, `append_hook_error`, `compute_event_id`
- `scripts/stop.py` — Stop/StopFailure/SubagentStop/PreCompact 공용 진입 (safe_main)
- `scripts/pre_compact.py` — stop.safe_main 위임 래퍼
- `scripts/session_start.py` — consolidation + MEMORY.md + 훅 에러 요약 주입
- `scripts/consolidate.py` — buffer → patterns/lessons/rules 승격 (문자열 유사도)
- `templates/` — MEMORY/STATE/TASKS 초기 템플릿
- `tests/` — pytest 스위트

## 원자성 / 동시성 보장

- 같은 프로젝트에서 여러 Claude Code 세션을 동시에 열어도 안전.
- `append_buffer_turn`은 `<project>/.memory/.lock` 내부에서 수행 — concurrent Stop 이벤트 간 file race 방지.
- 파일명에 `timestamp_ns + 8자 event_hash` 포함 → 같은 이벤트의 중복 저장(idempotency)과 동시 저장(unique)을 동시에 보장.
- 예외 발생 시 `_hook_errors.jsonl`에 JSON line append, 훅은 exit 0으로 조용히 종료 → 메모리 실패가 Claude 작업을 막지 않음.
