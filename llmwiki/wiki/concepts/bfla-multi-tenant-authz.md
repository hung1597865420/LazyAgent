---
title: BFLA Multi-Tenant Authorization
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Trong môi trường đa tenant, action admin có thể bị enforce chỉ bằng header/subdomain.

Kiểm tra:
- Giữ nguyên token nhưng đổi selector tenant qua header/subdomain
- Thử cross-tenant admin action

Nguyên tắc:
- Tenant admin phải được xác minh từ context server, không từ selector client