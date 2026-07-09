---
title: IDOR Microservice Headers
type: entity
related: [[IDOR]]
---

Các header liên quan đến microservices/gateways được nhắc đến:

- `X-User-Id`
- `X-Organization-Id`
- `X-Tenant-ID`

Chúng có thể bị trust sai hoặc bị override/remove để gây token/context confusion.