---
title: NoSQL Injection
type: concept
related: [[NoSQL Injection Attack Surface]]
---

NoSQL injection là lỗi khi input của người dùng ảnh hưởng trực tiếp đến cấu trúc truy vấn NoSQL thay vì chỉ là giá trị dữ liệu.

Đặc điểm chính:
- operator injection như `$gt`, `$regex`, `$where`
- structure injection bằng JSON sub-documents
- GraphQL resolvers có thể truyền biến thẳng vào NoSQL filter

Phòng tránh:
- schema validation
- parameterized equivalents
- không bao giờ pass raw user input như query object