# memory-init — 다른 PC로 이식하는 방법

이 스킬을 새 PC / 새 사용자 계정에 설치하는 절차.

## 사전 요구사항

- **Claude Code** 설치되어 있음
- **Python 3.9 이상** (`python --version` 으로 확인)
- **PyYAML**: `pip install pyyaml`

## 설치 절차

### 1. 스킬 디렉토리 배치

이 폴더(`memory-init/` 전체)를 target PC의 `~/.claude/skills/memory-init/` 아래에 둡니다.

**git으로 가져오는 경우 (권장):**
```bash
cd ~/.claude/skills
git clone <your-repo-url> memory-init
```

**수동 복사:**
폴더 전체를 USB/Dropbox/scp로 옮겨 `~/.claude/skills/memory-init/`에 배치.

### 2. Python 의존성 설치

```bash
pip install pyyaml
```

### 3. 글로벌 부트스트랩

```bash
python ~/.claude/skills/memory-init/scripts/bootstrap.py install-global
```

이 명령이 자동으로 수행:
- `~/.claude/settings.json`에 `SessionStart`, `Stop`, `StopFailure` 훅 3개 등록
- `~/.claude/CLAUDE.md` 맨 아래에 `<!-- memory-init: BEGIN/END -->` 마커로 감싼 override 섹션 추가 (Claude가 `.memory/`를 쓰도록 안내)

**idempotent**: 여러 번 실행해도 안전. 이미 설치된 엔트리는 중복 추가 안 함.

### 4. 설치 검증 (선택)

```bash
cd ~/.claude/skills/memory-init
python -m pytest tests/ -v
```

25 passed가 나와야 정상.

### 5. 프로젝트 초기화

메모리 시스템을 쓰고 싶은 각 프로젝트마다:

```bash
cd /path/to/project
python ~/.claude/skills/memory-init/scripts/bootstrap.py init-project .
```

`<project>/.memory/` 디렉토리 구조가 생성됨:
```
.memory/
├── MEMORY.md
├── STATE.md
├── TASKS.md
├── .meta.json
├── rules/
├── lessons/
├── patterns/
├── _buffer/
└── _archive/
```

### 6. Claude Code 세션 시작

그 프로젝트 디렉토리에서 Claude Code를 시작하면 자동으로:
- SessionStart 훅이 `MEMORY.md` 인덱스를 system prompt에 주입
- Stop 훅이 매 턴마다 `_buffer/`에 에피소드 기록
- 다음 SessionStart가 catch-up consolidation 실행

## 이식 시 주의사항

### 가져가지 말아야 할 것

- `~/.claude/settings.json`: PC마다 다른 설정(OMC, 다른 스킬 훅). `install-global`이 안전하게 섹션 추가.
- `~/.claude/CLAUDE.md`: 위와 동일. `install-global`이 마커 블록만 추가.
- 다른 프로젝트의 `.memory/` 데이터: 프로젝트별 고유 데이터. 같은 프로젝트를 두 PC에서 공유하고 싶다면 프로젝트 디렉토리 전체를 동기화 (git / GDrive / Syncthing 등).

### 가져가야 하지만 자동 처리되는 것

- 훅 경로의 절대경로: `bootstrap.py`의 `install-global`이 target PC의 `$HOME`을 기반으로 자동 해석. 이전 PC의 경로를 가져오지 않음.

### Windows vs Unix

- **하드코딩된 backslash는 없음**. 훅 커맨드는 `Path.as_posix()`로 forward slash 사용. Windows Python + Git Bash 호환.
- **파일 락**은 `sys.platform` 분기로 자동 선택:
  - Windows → `msvcrt.locking`
  - Linux/macOS → `fcntl.flock`

### Python 의존성 주의

- **PyYAML이 반드시 필요**. 없으면 `parse_memory_index`, `render_memory_index` 등이 전부 실패.
- `pytest`는 테스트 실행 시에만 필요 (production 실행엔 불필요).

## 업데이트

스킬이 진화하면 target PC에서:

```bash
cd ~/.claude/skills/memory-init
git pull       # git으로 설치한 경우
python -m pytest tests/ -v      # 회귀 확인
python scripts/bootstrap.py install-global    # 혹시 훅/CLAUDE.md 포맷이 바뀌었다면 재설치
```

`install-global`을 재실행해도 기존 마커 블록만 교체되므로 안전.

## 제거 방법

완전히 지우고 싶다면:

1. `~/.claude/CLAUDE.md`에서 `<!-- memory-init: BEGIN -->` ~ `<!-- memory-init: END -->` 블록 삭제
2. `~/.claude/settings.json`에서 `SessionStart`, `Stop`, `StopFailure` 항목 중 `session_start.py`/`stop.py`를 참조하는 엔트리 삭제
3. `~/.claude/skills/memory-init/` 디렉토리 삭제
4. 각 프로젝트의 `.memory/` 디렉토리 삭제 (데이터도 지울 거면)

## 현재 포함된 모듈

- `SKILL.md` — 스킬 정의 및 description (Claude Code가 자동 인식)
- `scripts/memory_ops.py` — 파일 I/O 유틸 + 크로스 플랫폼 파일 락
- `scripts/consolidate.py` — consolidation 파이프라인 (similarity, promotion, 파일 락)
- `scripts/bootstrap.py` — install-global + init-project CLI
- `scripts/session_start.py` — SessionStart 훅 어댑터
- `scripts/stop.py` — Stop / StopFailure 훅 어댑터
- `templates/MEMORY.md.tmpl` / `STATE.md.tmpl` / `TASKS.md.tmpl`
- `tests/` — pytest 25 test suite

## 디자인 문서

전체 설계 배경은 원본 저장소의 `docs/superpowers/specs/2026-04-15-memory-system-design.md` 참조.

## 원자성 / 동시성 보장

- 같은 프로젝트에서 **여러 Claude Code 세션을 동시에 열어도 안전**합니다.
- `<project>/.memory/.lock` 파일을 통한 크로스 프로세스 배타 락으로 `run_consolidation`과 `write_entry`가 직렬화됩니다.
- 타임아웃 5초, 실패 시 `TimeoutError`.
- 프로세스가 죽어도 OS가 락을 해제 (dead-lock 없음).
