---
title: Business Logic Bypass Techniques
type: concept
related: [[Business Logic Flaws]]
---

Các kỹ thuật bypass thường dùng trong business logic testing:

- Content-type switching: JSON/form/multipart
- Method alternation: GET đổi state, method override
- Client recomputation: totals/taxes/discounts do client tính
- Cache/gateway differentials: stale decisions không identity-aware

Mục tiêu là tìm code path hoặc decision path yếu hơn.