---
title: WebSocket Gateway Security
type: concept
related: [[NestJS Attack Surface]]
---

WebSocket gateway trong NestJS không tự động thừa hưởng guard của HTTP controller.

Rủi ro chính:
- Không khai báo `@UseGuards` cho gateway
- Chỉ auth ở `handleConnection` nhưng không kiểm tra ở message handler
- Room/namespace authorization yếu, cho phép join room không thuộc về user
- `@SubscribeMessage()` dựa vào connection-level auth thay vì per-message validation

Cách kiểm tra:
- So sánh quyền giữa HTTP và WebSocket cho cùng chức năng
- Thử gửi message khi chưa auth
- Kiểm tra authorization ở từng message và từng room join