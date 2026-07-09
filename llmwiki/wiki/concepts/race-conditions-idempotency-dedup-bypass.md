---
title: Idempotency and Dedup Bypass
type: concept
related: [[Race Conditions]]
---

Các lỗi idempotency/dedup thường xảy ra khi:

- idempotency key scope không đủ chặt
- store ghi sau khi request đã được xử lý
- dedup chỉ drop response nhưng side effects vẫn xảy ra

Đây là nguyên nhân phổ biến của duplicate side effects.