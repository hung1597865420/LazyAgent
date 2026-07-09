---
title: Business Logic Quotas, Limits, and Inventory
type: concept
related: [[Business Logic Flaws]]
---

Quotas, limits, và inventory dễ bị khai thác khi reset thời gian hoặc đồng bộ yếu.

Rủi ro:
- Off-by-one và time-bound resets
- Reservation/hold leaks
- Backorder logic inconsistencies
- Distributed counters không strong consistency dẫn đến double-consumption

Nguyên tắc:
- Counter và reservation phải nhất quán theo tenant/user/resource