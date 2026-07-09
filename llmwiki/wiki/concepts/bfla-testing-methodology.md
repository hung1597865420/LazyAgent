---
title: BFLA Testing Methodology
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Quy trình kiểm thử BFLA:

1. Build Actor × Action matrix: unauth, basic, premium, staff/admin
2. Obtain tokens/sessions cho từng role
3. Exercise mọi action qua REST/GraphQL/gRPC/WebSocket và các encoding khác nhau
4. Vary headers và selectors: org/tenant/project; test gateway vs direct-to-service
5. Include background flows: jobs, webhooks, queues; xác minh re-validation

Mục tiêu là tìm nơi action bị cho phép sai role hoặc sai transport.