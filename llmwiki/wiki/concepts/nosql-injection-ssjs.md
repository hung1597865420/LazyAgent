---
title: Server-Side JavaScript Injection
type: concept
related: [[NoSQL Injection]]
---

Một số NoSQL engine cho phép server-side JavaScript qua các operator như `$where`, `$function`, `$accumulator`.

Rủi ro:
- thực thi logic JS trên server
- timing oracle
- DoS nếu có vòng lặp vô hạn hoặc regex nặng

Cần kiểm tra trạng thái `javascriptEnabled` trước khi thử payload.