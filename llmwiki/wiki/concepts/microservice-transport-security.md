---
title: Microservice Transport Security
type: concept
related: [[NestJS Attack Surface]]
---

Các transport microservice của NestJS như TCP, Redis, NATS, MQTT, gRPC, Kafka thường bị xem là nội bộ nhưng vẫn có thể bị tấn công nếu network-accessible.

Rủi ro:
- `@MessagePattern` và `@EventPattern` không có guard
- Message có thể được inject trực tiếp qua transport
- `ValidationPipe` chỉ cấu hình cho HTTP, khiến payload microservice không được validate

Kiểm tra:
- So sánh bảo vệ giữa HTTP và microservice handlers
- Xác minh transport có thể truy cập từ mạng hay không
- Kiểm tra validation trên payload message