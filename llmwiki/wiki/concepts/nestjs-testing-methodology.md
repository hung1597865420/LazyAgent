---
title: NestJS Security Testing Methodology
type: concept
related: [[NestJS Attack Surface]]
---

Quy trình kiểm thử bảo mật cho NestJS:

1. Enumerate: lấy Swagger/OpenAPI, map controllers, resolvers, gateways
2. Guard audit: kiểm tra stack decorator theo từng method
3. Matrix testing: test unauth/user/admin × HTTP/WS/microservice
4. Validation probing: gửi extra fields, sai kiểu, nested objects, arrays
5. Transport parity: cùng một operation qua HTTP, WebSocket, microservice
6. Module boundaries: kiểm tra provider có truy cập chéo module không
7. Serialization check: so sánh entity thô với response API

Mục tiêu là phát hiện sai lệch giữa guard, validation, transport, và module boundary.