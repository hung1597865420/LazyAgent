---
title: Race Conditions Reconnaissance Signals
type: entity
related: [[Race Conditions Testing Methodology]]
---

Các tín hiệu nhận biết race window:

- sequential request fail nhưng parallel succeed
- duplicate rows
- negative counters
- over-issuance
- inconsistent aggregates
- distinct response shapes/timings
- audit logs out of order
- multiple 2xx cho cùng intent
- missing hoặc duplicate correlation IDs