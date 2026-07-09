---
title: Redis Command Injection
type: concept
related: [[NoSQL Injection]]
---

Redis command injection xảy ra khi lệnh Redis được dựng bằng string concatenation thay vì API an toàn.

Kỹ thuật thường dùng:
- chèn newline `\r\n`
- smuggle thêm command mới qua RESP protocol

Đây là dạng command smuggling hơn là query operator injection.