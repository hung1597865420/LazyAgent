---
title: Model Roles — Agent Harness
type: concept
related: [[harness-architecture]]
---

| Tool | Model | Khi nào dùng |
|---|---|---|
| consult | grok-4-reasoning | Schema DB mới, auth/RLS, API design 3+ endpoints, chọn thư viện, tích hợp external, security, kiến trúc mới |
| alt_implementation | Kimi-K2.6 + gpt-5.4 | Module mới >30 dòng sẽ reuse, không chắc approach, refactor lớn |
| panel_review | gpt-5.3-codex ×3 + gpt-5.4-pro-2 | Bắt buộc trước khi báo hoàn thành (1 lần/batch) |
| suggest_fix | gpt-5.4-2 | Debug bí sau 1-2 lần thử |
| ask_codebase | gpt-5.4-pro | Hiểu flow xuyên nhiều file codebase lớn |
| quick_task | gpt-5.4-mini | Fixtures, mock data, boilerplate, docs |

## Trigger tự động
- **consult**: 8 trường hợp cụ thể trong CLAUDE.md — không đợi user nhắc
- **alt_implementation**: 3 trường hợp — gọi song song với consult nếu cả 2 thỏa
- **panel_review**: LUÔN gọi trước khi báo xong (trừ ngoại lệ: docs/config <10 dòng)
