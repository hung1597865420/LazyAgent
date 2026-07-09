---
title: NestJS Controller and Transport Types
type: entity
related: [[NestJS Attack Surface]]
---

Các loại controller và transport được nhắc đến:

- REST: `@Controller`, versioning URI/Header/MediaType
- GraphQL: `@Resolver`
- WebSocket: `@WebSocketGateway`
- Microservices: TCP, Redis, NATS, MQTT, gRPC, Kafka

Đây là các thực thể định nghĩa cách request đi vào hệ thống và cách auth phải được áp dụng.