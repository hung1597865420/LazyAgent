---
title: IDOR WebSocket and gRPC Fields
type: entity
related: [[IDOR]]
---

Các field trong WebSocket và gRPC được nhắc đến:

- WebSocket channel/topic names như `user_{id}`, `org_{id}`
- gRPC protobuf fields như `owner_id`, `tenant_id`

Đây là các reference cần được kiểm tra authorization ở server-side.