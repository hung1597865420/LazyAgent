---
title: BFLA Microservices Authorization
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Trong microservices, internal RPC thường tin upstream checks và bỏ qua re-validation.

Rủi ro:
- Reach internal RPC qua exposed endpoint hoặc SSRF
- Service downstream không re-enforce authz

Nguyên tắc:
- Mỗi service phải tự kiểm tra quyền tại boundary của nó