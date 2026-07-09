---
title: Redis RESP Injection
type: entity
related: [[Redis Command Injection]]
---

Redis RESP injection được nhắc đến qua newline injection:

- `\r\n`
- chèn thêm command mới vào chuỗi lệnh

Đây là cơ chế smuggling lệnh Redis.