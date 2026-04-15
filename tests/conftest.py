"""Shared pytest fixtures for memory-init tests."""
import os
import sys
from pathlib import Path

# scripts 모듈을 테스트에서 import 가능하게 추가
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """임시 .memory/ 디렉토리 생성. 각 테스트마다 독립된 경로."""
    memory = tmp_path / ".memory"
    memory.mkdir()
    (memory / "rules").mkdir()
    (memory / "lessons").mkdir()
    (memory / "patterns").mkdir()
    (memory / "_buffer").mkdir()
    (memory / "_archive").mkdir()
    return memory


@pytest.fixture
def sample_memory_index_content():
    """샘플 MEMORY.md 내용."""
    return """# Memory Index

## State
- STATE.md last updated 2026-04-15 — memory system design
- TASKS.md: 2 pending

## Rules

```yaml
- id: rule.naming.no-idx
  type: rule
  summary: "변수명에 _idx 접미사 금지"
  scope: local
  updated: 2026-04-15
  confidence: high
  tags: [naming]
  path: rules/naming.md
```

## Lessons

```yaml
- id: lesson.auth.cookie
  type: lesson
  summary: "same-site=strict는 OAuth 깨뜨림"
  scope: local
  updated: 2026-03-22
  confidence: high
  tags: [auth]
  path: lessons/auth-cookie.md
```

## Patterns

```yaml
```

## Promotion Candidates
"""
