---
title: Dangerous ORM APIs
type: entity
related: [[ORM and Query Builder Injection]]
---

Các API nguy hiểm được nhắc đến:

- `whereRaw`
- `orderByRaw`
- string interpolation into LIKE/IN/ORDER clauses
- identifier quoting for table/column names
- raw fragments in JSON containment operators
- unbound `IN (...)` lists