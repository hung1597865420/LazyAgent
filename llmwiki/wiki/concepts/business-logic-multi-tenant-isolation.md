---
title: Business Logic Multi-Tenant Isolation
type: concept
related: [[Business Logic Flaws]]
---

Multi-tenant isolation phải được enforce ở mọi thao tác stateful.

Rủi ro:
- Tenant-scoped counters/credits update thiếu tenant key
- Admin aggregate views cho phép tác động lên tenant khác

Nguyên tắc:
- Mọi query/update phải có tenant scoping rõ ràng