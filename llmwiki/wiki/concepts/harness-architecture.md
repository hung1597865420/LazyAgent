---
title: Agent Harness Architecture
type: concept
related: [[model-roles]], [[azure-foundry-integration]]
---

MCP server expose 6 tools cho Claude Code. Mỗi tool map sang 1 hoặc nhiều Azure AI Foundry model theo role.

## Flow

```
Claude Code → mcp_server.py (MCP protocol)
           → harness.py (chọn model, gọi song song nếu cần)
           → agents.py (Azure AI Foundry API calls)
           → Azure AI Foundry (10 deployments)
```

## Routing rules
- `consult` → Grok (deep reasoning) — gọi TRƯỚC implement khi có architecture decision
- `alt_implementation` → Kimi K2 + GPT song song — 2 phương án độc lập
- `panel_review` → GPT Codex ×3 + GPT Pro synthesize — bugs/edge/security
- `suggest_fix` → GPT-2 — root cause + diff patch
- `ask_codebase` → GPT Pro (1M context) — Q&A xuyên codebase lớn
- `quick_task` → GPT Mini — boilerplate, fixtures, docs

## Constraints
- Azure endpoint + API key: env var, không commit git
- Harness lỗi → tiếp tục task, không block, báo user ngắn gọn
- Không retry quá 1 lần khi timeout/rate-limit
