---
title: BFLA gRPC Abuse
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

gRPC cần authz ở method-level thông qua interceptors.

Rủi ro:
- Interceptor không enforce audience/roles
- Reflection làm lộ service/method và cho phép gọi admin method bị gateway ẩn

Nguyên tắc:
- Mỗi method phải tự enforce quyền, không dựa vào gateway