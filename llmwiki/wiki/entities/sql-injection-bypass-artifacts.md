---
title: SQLi Bypass Artifacts
type: entity
related: [[SQL Injection Bypass Techniques]]
---

Các artifact bypass được nhắc đến:

- `/**/`
- `/**/!00000`
- newlines
- tabs
- ideographic space `0xe3 0x80 0x80`
- `UN/**/ION`
- `U%4eION`
- scientific notation
- hex literals
- double URL encoding
- mixed Unicode normalizations
- `char()`
- `CONCAT_ws`
- subselects
- derived tables
- CTEs
- lateral joins