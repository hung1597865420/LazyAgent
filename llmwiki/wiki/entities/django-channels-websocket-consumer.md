---
title: Django Channels WebSocket Consumer
type: entity
related: [[Channels WebSocket Security]]
---

WebSocket consumer trong Django Channels là thực thể xử lý kết nối và message qua ASGI.

Các điểm cần chú ý:
- Xác thực kết nối
- Tính tương đương quyền với HTTP endpoints
- Cách đặt group name
- Kiểm tra origin trong handshake

Đây là nơi có thể phát sinh lỗi authorization nếu không đồng bộ với REST API.