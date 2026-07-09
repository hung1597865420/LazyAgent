---
title: Optimistic Concurrency Evasion
type: concept
related: [[Race Conditions]]
---

Optimistic concurrency chỉ hiệu quả nếu `If-Match`, ETag, hoặc version field được kiểm tra nhất quán trên mọi code path.

Lỗi xảy ra khi:
- header/version là optional nhưng server bỏ qua
- version field chỉ được validate ở một số API
- REST và GraphQL xử lý khác nhau