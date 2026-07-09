---
title: BFLA Attack Surface
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Bề mặt tấn công của BFLA gồm:

- Vertical authz: user thường truy cập được action chỉ dành cho admin/staff
- Feature gates: toggle chỉ được enforce ở edge/UI, không ở core service
- Transport drift: REST, GraphQL, gRPC, WebSocket có kiểm tra không đồng nhất
- Gateway trust: backend tin các header như `X-User-Id`/`X-Role` do proxy inject
- Background workers/jobs: thực thi action mà không re-check authz