---
title: Agent Harness Architecture
type: concept
related: [[model-roles]], [[router-foundry-integration]]
---

MCP server expose 6 tools cho Claude Code. Mỗi tool map sang 1 hoặc nhiều 9Router Proxy model theo role.

## Flow

```
Claude Code → mcp_server.py (MCP protocol)
           → harness.py (chọn model, gọi song song nếu cần)
           → agents.py (9Router Proxy API calls)
           → 9Router Proxy (10 deployments)
```

## Routing rules
- `consult` → Sonnet (deep reasoning) — gọi TRƯỚC implement khi có architecture decision
- `alt_implementation` → Gemini 3.5 High + Sonnet — 2 phương án độc lập
- `panel_review` → Gemini 3.5 High reviewer/tester + Sonnet security/integrity — bugs/edge/security
- `suggest_fix` → Gemini 3.5 High — root cause + diff patch
- `ask_codebase` → Gemini 3.5 High, fallback Sonnet — Q&A xuyên codebase lớn
- `quick_task` → Gemini 3.5 Low — boilerplate, fixtures, docs/non-code

## Constraints
- 9Router endpoint + API key: env var, không commit git
- Harness lỗi → tiếp tục task, không block, báo user ngắn gọn
- Không retry quá 1 lần khi timeout/rate-limit
