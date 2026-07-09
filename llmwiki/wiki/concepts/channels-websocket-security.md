---
title: Channels WebSocket Security
type: concept
related: [[Django]]
---

Django Channels và WebSocket cần được bảo vệ tương đương với HTTP endpoints, nhưng thường bị bỏ sót trong kiểm tra auth.

Rủi ro chính:
- Consumer cho phép kết nối mà không kiểm tra session/auth tương đương HTTP
- Group name được tạo từ input người dùng, cho phép subscribe nhầm channel của người khác
- Thiếu origin validation trong WebSocket handshake

Cách kiểm tra:
- So sánh quyền giữa REST và WebSocket cho cùng một resource
- Thử kết nối không auth hoặc với origin khác
- Kiểm tra cách đặt tên group/channel

Khuyến nghị:
- Áp dụng authorization giống REST
- Validate origin
- Không dùng dữ liệu người dùng trực tiếp để đặt group name