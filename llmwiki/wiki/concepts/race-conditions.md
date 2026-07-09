---
title: Race Conditions
type: concept
related: [[Race Conditions Attack Surface]]
---

Race condition là lỗi đồng thời khi nhiều request hoặc luồng cùng thao tác lên state chung mà không có atomicity, locking, isolation, hoặc idempotency đầy đủ.

Hệ quả chính:
- duplicate state changes
- quota bypass
- financial abuse
- privilege errors

Nguyên tắc cốt lõi:
- coi mọi read–modify–write và multi-step workflow là adversarially concurrent