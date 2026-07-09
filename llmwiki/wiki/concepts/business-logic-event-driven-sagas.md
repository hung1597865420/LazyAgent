---
title: Business Logic Event-Driven Sagas
type: concept
related: [[Business Logic Flaws]]
---

Trong saga/event-driven flows, thiếu idempotency hoặc compensation gaps có thể tạo side effects trùng lặp hoặc trạng thái sai.

Rủi ro:
- Trigger compensation mà không có original success
- Execute success hai lần mà không compensation
- Outbox/Inbox thiếu idempotency
- Cron/backfill jobs chạy ngoài request-time authorization

Nguyên tắc:
- Mọi bước saga phải có guard và idempotency rõ ràng