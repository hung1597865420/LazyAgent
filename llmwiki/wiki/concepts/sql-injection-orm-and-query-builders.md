---
title: ORM and Query Builder Injection
type: concept
related: [[SQL Injection]]
---

ORM và query builder vẫn có thể bị SQLi nếu raw fragments hoặc string interpolation lọt qua.

Các điểm nguy hiểm:
- `whereRaw`
- `orderByRaw`
- interpolation vào LIKE/IN/ORDER clauses
- identifier quoting cho table/column names
- partial parameterization nơi operator hoặc list chưa được bind