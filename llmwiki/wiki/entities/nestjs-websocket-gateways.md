---
title: NestJS WebSocket Gateways
type: entity
related: [[WebSocket Gateway Security]]
---

Các thực thể WebSocket trong NestJS gồm:

- `@WebSocketGateway`
- `handleConnection`
- `@SubscribeMessage()`
- room/namespace authorization

Chúng đại diện cho lớp giao tiếp thời gian thực cần kiểm tra auth và authorization riêng.