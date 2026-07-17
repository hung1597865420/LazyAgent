---
title: Model Roles — Agent Harness
type: concept
related: [[harness-architecture]]
---

| Tool | Model | Khi nào dùng |
|---|---|---|
| consult | ag/claude-sonnet-4-6 | Schema DB mới, auth/RLS, API design 3+ endpoints, chọn thư viện, tích hợp external, security, kiến trúc mới |
| alt_implementation | ag/gemini-3-flash-agent + ag/claude-sonnet-4-6 | Module mới >30 dòng sẽ reuse, không chắc approach, refactor lớn |
| panel_review | High reviewer/tester + Sonnet security/integrity | Bắt buộc trước khi báo hoàn thành (1 lần/batch) |
| suggest_fix | ag/gemini-3-flash-agent | Debug bí sau 1-2 lần thử |
| ask_codebase | ag/gemini-3-flash-agent → ag/claude-sonnet-4-6 | Hiểu flow xuyên nhiều file codebase lớn |
| quick_task | ag/gemini-3.5-flash-extra-low | Fixtures, mock data, boilerplate, docs/non-code |

## Trigger tự động
- **consult**: 8 trường hợp cụ thể trong CLAUDE.md — không đợi user nhắc
- **alt_implementation**: 3 trường hợp — gọi song song với consult nếu cả 2 thỏa
- **panel_review**: LUÔN gọi trước khi báo xong (trừ ngoại lệ: docs/config <10 dòng)
