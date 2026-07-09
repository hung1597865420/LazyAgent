---
title: BFLA Cache Key Confusion
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Authorization decisions được cache ở edge có thể bị tái sử dụng sai giữa các user.

Rủi ro:
- Cache key không bao gồm session/role/tenant đầy đủ
- Vary header không đúng

Nguyên tắc:
- Kiểm tra cache behavior khi swap session hoặc principal