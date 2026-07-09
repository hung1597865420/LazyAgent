---
title: NoSQL Injection False Positives
type: concept
related: [[NoSQL Injection]]
---

Các trường hợp dễ nhầm:

- query builder cast input thành string
- sanitizer loại bỏ operator keys
- field bị cast thành string nên thành `[object Object]`
- response khác do validation error chứ không phải operator execution

Cần xác minh rằng payload thật sự tới driver/database.