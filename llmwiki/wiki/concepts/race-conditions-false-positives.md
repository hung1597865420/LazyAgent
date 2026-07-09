---
title: Race Conditions False Positives
type: concept
related: [[Race Conditions]]
---

Các trường hợp không nên kết luận là race condition:

- operation thật sự idempotent với ETag/version checks hoặc unique constraints
- serializable transactions hoặc advisory locks/queues đúng
- visual-only glitches không đổi state bền vững
- rate limits atomic counters từ chối đúng số dư thừa