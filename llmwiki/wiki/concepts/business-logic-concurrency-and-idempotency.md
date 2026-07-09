---
title: Business Logic Concurrency and Idempotency
type: concept
related: [[Business Logic State Machine Abuse]]
---

Concurrency và idempotency là nguồn lỗi phổ biến trong business logic.

Rủi ro:
- Parallelize identical operations để bypass atomic checks
- Idempotency key chỉ scoped theo path mà không theo principal
- Idempotency lưu trong cache nên dễ mất hoặc bị reuse sai
- Message reprocessing làm duplicate fulfillment/refund

Nguyên tắc:
- Idempotency phải gắn với principal, resource, và action
- Queue/job worker phải có guard chống re-run