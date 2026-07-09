---
title: NoSQL Injection Validation
type: concept
related: [[NoSQL Injection Testing Methodology]]
---

Validation cần chứng minh:

- authentication bypass
- blind extraction của secret verifiable
- ít nhất hai payload khác nhau cùng hoạt động
- before/after rõ ràng
- timing differential với `$where` nếu có

Chỉ lỗi validation hoặc response khác biệt chưa đủ để kết luận.