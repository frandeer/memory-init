# memory-init

> Repository: https://github.com/frandeer/memory-init

Claude Code용 **영구적이지만 최적화된 메모리 시스템**. 세션을 넘어 축적되고, 자동으로 압축·갱신·전파되는 경험 기반 기억 레이어.

> 텍스트를 저장하지 말고 **판단 기준**을 저장하라.
> 집 짓기의 모든 망치질이 아니라 "이 지반에는 이 기초가 맞더라"의 경력이 쌓이는 방식.

## 이게 왜 필요한가

- 새 Claude 세션이 시작될 때마다 "아무것도 모르는 상태"로 돌아감 → 같은 설명 반복
- 프로젝트별 규칙, 과거 시행착오, 현재 진행상황이 매 세션 날아감
- Claude Code 기본 auto-memory는 경로에 묶여 있고 실질적으로 잘 안 쌓임
- CLAUDE.md는 300줄 권장선이라 많이 담으면 컨텍스트가 터짐

**이 스킬의 해법:**
- 프로젝트 루트에 `.memory/` 디렉토리 → 세션을 넘어 살아남는 로컬 파일
- 작은 인덱스(`MEMORY.md` ≤120줄)만 매 세션 자동 로드, 상세는 on-demand
- Stop 훅이 매 턴마다 버퍼에 에피소드 기록, SessionStart 훅이 버퍼를 장기 메모리로 자동 압축
- **rules / lessons / patterns** 3개 타입만 — 분류 혼란 없음
- 같은 주제가 2번 이상 독립 세션에서 반복되면 자동으로 `patterns/`로 승격 ("경력이 쌓이는 방식")

## Quick start

### 처음 1회 (글로벌)

```bash
pip install pyyaml
python ~/.claude/skills/memory-init/scripts/bootstrap.py install-global
```

이게 끝. `~/.claude/settings.json`에 훅 3개 등록 + `~/.claude/CLAUDE.md`에 override 섹션 추가.

### 새 프로젝트마다

```bash
cd /path/to/project
python ~/.claude/skills/memory-init/scripts/bootstrap.py init-project .
```

또는 Claude와 대화로: *"이 프로젝트에 memory-init 해줘"*

그 디렉토리에서 Claude Code 세션을 열면 자동으로 작동.

## 일상 사용법

### 규칙 기록

```
User: 이거 규칙이야. 이 프로젝트에서는 DB migration을 항상 staging에서 먼저 돌려
Claude: [rules/db-migration-staging-first.md 생성, MEMORY.md 업데이트]
```

다음 세션에서도, 다른 날에도 Claude는 이 규칙을 알고 있음.

### 시행착오 기록

```
User: 방금 auth 쿠키 SameSite=strict 설정했다가 OAuth 콜백 다 깨졌어. 롤백했음
Claude: [lessons/auth-cookie-same-site.md 저장 — 다음부터 이 실수 방지]
```

### 현재 진행상황 파악

```
User: 지금 어디까지 했지?
Claude: [STATE.md 읽고 요약]
```

새 세션을 시작할 때 `resume`/`compact` 상태면 STATE.md가 자동 주입되므로 굳이 물어볼 필요도 없음.

### 앞으로 할 일 분류

```
User: 다음에 할 일 정리해줘
Claude: [TASKS.md에 Active/Pending/Backlog/Blocked로 분류해 저장]
```

### 메모리 훑어보기

Claude가 매 세션 `MEMORY.md` 인덱스를 자동 로드하므로 평소엔 신경 쓸 필요 없음. 직접 보고 싶으면:

```bash
cat /path/to/project/.memory/MEMORY.md   # 인덱스
ls /path/to/project/.memory/rules/         # 규칙 파일들
ls /path/to/project/.memory/lessons/       # 교훈 파일들
ls /path/to/project/.memory/patterns/      # 자동 승격된 패턴
```

Obsidian으로 `.memory/` 디렉토리를 vault로 열어서 시각적으로 탐색해도 됨. 표준 마크다운 + YAML frontmatter라 자연스럽게 작동.

## 자동 작동 흐름

```
새 Claude 세션 시작
  ↓
SessionStart 훅
  ↓
  ├─ .memory/_buffer/ 에 미처리 에피소드 있음? → Python consolidator 실행
  │   ├─ 같은 테마가 2+ 독립 세션에서 반복? → patterns/로 자동 승격
  │   ├─ 중복/모순 감지 (보수적으로 카운트만)
  │   └─ .consolidated sentinel 업데이트
  │
  └─ MEMORY.md (≤120줄 인덱스) 를 컨텍스트에 주입
       + (resume/compact일 때만) STATE.md 본문도 주입

[세션 진행 — Claude가 필요할 때 rules/*.md, lessons/*.md 를 on-demand 로드]

매 턴 종료 (Stop / StopFailure 훅)
  ↓
  └─ 이번 턴 에피소드를 _buffer/session-<id>-turn-<n>.md 에 atomic write
     (세션이 강제 종료돼도 버퍼는 디스크에 살아남음)
```

**핵심 보장:**
- 하드킬/크래시 내성: Stop 훅이 턴마다 append → 최악의 경우 in-flight 턴 1개만 유실
- 동시 세션 안전: `.memory/.lock` 크로스 프로세스 배타 락 (Windows `msvcrt.locking` / Unix `fcntl.flock`)
- 토큰 예산: 매 세션 자동 로드는 인덱스 + (선택적) STATE 한 줄, 합쳐서 ≤150줄 / 25KB 하드 상한

## 파일 레이아웃

```
<project-root>/
└── .memory/
    ├── MEMORY.md         # 인덱스 (≤120줄, 매 세션 자동 로드)
    ├── STATE.md          # 현재 진행상황 (resume/compact 시 자동 주입)
    ├── TASKS.md          # 분류된 백로그
    ├── .meta.json        # 운영 메타데이터 (sidecar)
    ├── .lock             # 크로스 프로세스 락 파일
    │
    ├── rules/*.md        # 규칙·선호·결정 (`rationale` 포함)
    ├── lessons/*.md      # 시행착오·교훈·anti-pattern
    ├── patterns/*.md     # 자동 승격된 일반화
    │
    ├── _buffer/          # 세션 턴별 에피소드 (consolidation 대상)
    └── _archive/         # prune된 메모리 (삭제 아닌 보관)
```

## 메모리 타입 설명

| 타입 | 언제 쓰는가 | 예시 |
|------|-------------|------|
| **rule** | "앞으로 항상/절대 X" — 영구 제약, 선호, 결정 | "변수명에 `_idx` 접미사 금지" |
| **lesson** | "X 시도했는데 Y 때문에 깨졌다" — 같은 실수 반복 방지 | "same-site=strict는 OAuth 콜백 깨뜨림" |
| **pattern** | 반복 관찰된 일반화 — **자동 승격만** | "429/5xx에는 capped exponential backoff + jitter" |

수동 저장은 rule + lesson만. pattern은 consolidation이 2+ 독립 세션에서 같은 테마를 보면 알아서 생성.

## 동시 세션

같은 프로젝트에 Claude Code 창 여러 개를 동시에 열어도 안전합니다. `.memory/.lock`으로 `run_consolidation`과 `write_entry`가 직렬화되고, 타임아웃 5초 실패 시 `TimeoutError` 발생 (무한 대기 없음). 프로세스 크래시 시 OS가 락 자동 해제.

## 다른 PC로 옮기려면

`INSTALL.md` 참조. 요약:

```bash
cd ~/.claude/skills
git clone https://github.com/frandeer/memory-init.git
pip install pyyaml
python ~/.claude/skills/memory-init/scripts/bootstrap.py install-global
```

그게 전부. `settings.json`, `CLAUDE.md`는 bootstrap 스크립트가 target PC의 경로로 자동 갱신.

## 트러블슈팅

### 새 세션에 메모리가 안 보임

```bash
# 훅이 등록됐는지 확인
python -c "import json; d = json.load(open('~/.claude/settings.json'.replace('~', __import__('os').path.expanduser('~')))); print([h['hooks'][0]['command'] for h in d.get('hooks', {}).get('SessionStart', [])])"

# .memory/ 디렉토리 확인
ls <your-project>/.memory/MEMORY.md
```

인덱스 파일이 없거나 훅이 누락되면 bootstrap 재실행:
```bash
python ~/.claude/skills/memory-init/scripts/bootstrap.py install-global
python ~/.claude/skills/memory-init/scripts/bootstrap.py init-project <project>
```

### Windows에서 "can't open file" 에러

Backslash escape 이슈. `bootstrap.py` 최신 버전 (`b30056c` 이후)으로 업데이트하고 `install-global` 재실행. 훅 경로가 forward slash로 다시 쓰임.

### 버퍼가 커지는데 consolidation이 안 돌아감

SessionStart 훅이 매 세션 시작 시 catch-up consolidation 실행. 한 세션이 오래 지속되면 그동안은 compaction이 없음. 완전히 수동으로 트리거하고 싶으면:

```bash
python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / '.claude' / 'skills' / 'memory-init' / 'scripts'))
from consolidate import run_consolidation
print(run_consolidation(Path('<your-project>/.memory')))
"
```

### 메모리 시스템 일시 비활성화

특정 프로젝트에서 잠시 끄고 싶으면 `.memory/` 디렉토리 이름을 `.memory.disabled/`로 바꿉니다. 훅이 no-op fallback으로 동작 (스펙 §6.2). 다시 켜려면 이름 원복.

### 완전 제거

`INSTALL.md`의 "제거 방법" 섹션 참조.

## 더 깊은 내용

- `INSTALL.md` — 다른 PC 이식 절차
- `SKILL.md` — 스킬 정의 (Claude Code가 읽음)
- 원본 설계 문서: `D:/lab/document/docs/superpowers/specs/2026-04-15-memory-system-design.md`
- 구현 계획: `D:/lab/document/docs/superpowers/plans/2026-04-15-memory-system.md`

## 한계와 Post-MVP 항목

현재 MVP는 의도적으로 최소 기능만 포함:
- `/memory` 런타임 커맨드 (status / log / prune / promote / search) **없음**
- `/memory refine` 서브에이전트 기반 semantic curation **없음**
- `~/.claude/.memory/global/` 글로벌 패턴 레이어 (크로스 프로젝트 승격) **없음**
- Monorepo 시 `.memory/` 위치 자동 감지 **없음**
- 중복/모순 자동 병합은 **탐지만**, 실제 병합은 수동 (안전을 위해)

이 중 필요한 게 생기면 별도 spec+plan 사이클로 추가 가능.
