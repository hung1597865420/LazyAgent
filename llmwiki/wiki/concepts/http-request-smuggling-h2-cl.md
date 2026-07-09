---
title: H2.CL Request Smuggling
type: concept
related: [[HTTP Request Smuggling]]
---

H2.CL xảy ra khi HTTP/2 front-end downgrade sang HTTP/1.1 và inject `content-length` regular header vào request gửi xuống back-end.

Đặc điểm:
- HTTP/2 không có ambiguity TE/CL nội tại như HTTP/1.1
- Nhưng downgrade có thể tạo ra mismatch giữa `content-length` và body thật
- `content-length` trong HTTP/2 là regular header, không phải pseudo-header

Đây là biến thể hiện đại có tác động cao.