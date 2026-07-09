---
title: Insecure Deserialization Testing Methodology
type: concept
related: [[Insecure Deserialization]]
---

Quy trình kiểm thử:

1. Find sinks
2. Confirm format
3. Use safe oracle
4. Select gadget
5. Build minimal PoC
6. Focus on session/cookie stores

Mục tiêu là chứng minh sink thật sự nhận object graph do attacker kiểm soát.