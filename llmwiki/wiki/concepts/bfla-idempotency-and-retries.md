---
title: BFLA Idempotency and Retries
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Retry hoặc replay có thể làm privileged action được áp dụng nhiều lần nếu mỗi lần không kiểm tra actor.

Rủi ro:
- Finalize/approve endpoint áp state mà không xác minh người thực thi ở mỗi call

Nguyên tắc:
- Mỗi request/retry phải re-check authorization