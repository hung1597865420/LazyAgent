---
title: Front-End Security Control Bypass
type: concept
related: [[HTTP Request Smuggling]]
---

Request smuggling có thể bypass các security controls ở front-end proxy.

Ví dụ:
- authentication bypass
- IP restriction bypass
- request được back-end xử lý mà không qua kiểm tra ở front-end

Nguyên tắc:
- Security decisions không được chỉ dựa vào hop đầu tiên nếu request có thể bị desync