---
title: Django ORM Query APIs
type: entity
related: [[ORM SQL Injection]]
---

Các API ORM được nhắc đến trong tài liệu gồm:

- `filter()`
- `Q` objects
- `raw()`
- `extra()`
- `RawSQL`
- annotations

Các API này là nơi cần chú ý khi xây dựng query động, đặc biệt nếu có ghép chuỗi hoặc nhận input từ người dùng.