---
title: Client-Side Prototype Pollution
type: concept
related: [[Prototype Pollution]]
---

Client-side prototype pollution ảnh hưởng đến browser logic khi properties bị pollute được đọc bởi UI hoặc DOM sinks.

Tác động thường gặp:
- auth bypass qua `user.isAdmin`
- DOM XSS
- cookie/session manipulation

Cần kiểm tra các gadget tiêu thụ property từ prototype thay vì object riêng lẻ.