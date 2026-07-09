---
title: Guard Bypass
type: concept
related: [[NestJS Attack Surface]]
---

Guard bypass xảy ra khi một route hoặc transport không được bảo vệ đúng cách bởi chuỗi guard của NestJS.

Các mẫu lỗi phổ biến:
- Method mới trong controller không có `@UseGuards` trong khi các method khác có
- `@Public()` làm global `AuthGuard` bỏ qua enforcement quá rộng
- Guard chỉ xử lý HTTP context và trả về `true` mặc định ở WebSocket hoặc RPC
- `SetMetadata` và decorator thực tế không khớp key metadata
- `applyDecorators()` vô tình ghi đè guard chặt hơn bằng guard lỏng hơn

Nguyên tắc kiểm tra:
- Audit guard theo global → controller → method
- So sánh hành vi giữa HTTP, WS, và RPC
- Kiểm tra metadata key và composition của decorators