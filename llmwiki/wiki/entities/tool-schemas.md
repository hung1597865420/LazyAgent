---
title: MCP Tool Schemas
type: entity
related: [[harness-architecture]], [[model-roles]]
---

## consult
```python
# Input
question: str       # câu hỏi architecture/design
context: str        # relevant code + decisions.md content
files: list[str]    # paths đã đọc

# Output
recommendation: str
rationale: str
alternatives: list[str]
```

## alt_implementation
```python
# Input
task: str           # mô tả module/component cần implement
context: str        # existing code context

# Output (2 implementations)
implementation_a: str   # Kimi K2
implementation_b: str   # GPT
comparison: str
```

## panel_review
```python
# Input
diff: str           # git diff hoặc toàn bộ files thay đổi

# Output
findings: list[Finding]  # critical/high/medium/low
synthesis: str
```

## suggest_fix
```python
# Input
code: str
error: str          # error message hoặc stack trace

# Output
root_cause: str
patch: str          # unified diff
```

## ask_codebase
```python
# Input
question: str
index_md: str       # nội dung index.md làm navigation

# Output
answer: str
relevant_files: list[str]
```

## quick_task
```python
# Input
task: str           # boilerplate, fixture, doc generation

# Output
result: str         # generated content
```
