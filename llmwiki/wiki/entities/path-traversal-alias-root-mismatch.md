---
title: Alias/Root Mismatch
type: entity
related: [[Path Traversal Bypasses]]
---

Các mismatch được nhắc đến:

- nginx alias không có trailing slash
- nested location cho phép `../` escape
- thử `/static/../etc/passwd`
- `..;` variants

Đây là lỗi cấu hình giữa web server và app path mapping.