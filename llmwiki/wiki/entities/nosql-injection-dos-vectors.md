---
title: NoSQL DoS Vectors
type: entity
related: [[Server-Side JavaScript Injection]]
---

Các vector DoS được nhắc đến:

- ReDoS với regex catastrophic backtracking
- large `$in` arrays
- infinite `$where` loops
- heavy aggregations với nhiều `$lookup`

Đây là các tác động phụ của NoSQL injection khi mục tiêu là làm chậm hoặc treo hệ thống.