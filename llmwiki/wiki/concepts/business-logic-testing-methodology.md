---
title: Business Logic Testing Methodology
type: concept
related: [[Business Logic Flaws]]
---

Quy trình kiểm thử business logic:

1. Enumerate state machine cho workflow quan trọng
2. Build Actor × Action × Resource matrix
3. Test transitions: skip, repeat, reorder, late mutation
4. Introduce variance: time, concurrency, channel, content-type
5. Validate persistence boundaries: services, queues, jobs

Mục tiêu là chứng minh vi phạm invariant với state change bền vững.