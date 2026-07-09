---
title: Differential Oracles
type: concept
related: [[Information Disclosure]]
---

Differential oracles là kỹ thuật so sánh phản hồi giữa owner, non-owner, và anonymous để suy ra sự tồn tại hoặc trạng thái của tài nguyên.

Tín hiệu thường dùng:
- status
- length
- `ETag`
- `Last-Modified`
- `Cache-Control`
- khác biệt giữa `HEAD` và `GET`
- `304` vs `200`

Mục tiêu là xác nhận existence/state mà không cần thấy full content.