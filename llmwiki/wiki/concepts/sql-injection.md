---
title: SQL Injection
type: concept
related: [[SQL Injection Attack Surface]]
---

SQL injection là lỗi khi input của người dùng đi vào câu lệnh SQL qua string concatenation hoặc query construction không an toàn.

Tài liệu nhấn mạnh các hướng khai thác hiện đại:
- parser differentials
- ORM/query-builder edges
- JSON/XML/CTE/JSONB surfaces
- out-of-band exfiltration
- blind channels

Nguyên tắc phòng tránh:
- bind parameters everywhere
- tránh dynamic identifiers
- validate tại đúng boundary giữa user input và SQL