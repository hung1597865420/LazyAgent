---
title: HTTP/2 Pseudo-Header and Frame Confusion
type: concept
related: [[HTTP Header Injection]]
---

HTTP/2 có thể tạo ra confusion khi downgrade sang HTTP/1.1 hoặc khi intermediary xử lý frame/pseudo-header không nhất quán.

Rủi ro:
- pseudo-headers như `:method`, `:path`, `:authority`, `:scheme` bị mishandle
- lowercase header names làm filter H1 case-sensitive bỏ sót
- HEADERS/CONTINUATION frame splitting gây khác biệt giữa intermediary và backend

Nguyên tắc:
- Phải kiểm tra đồng nhất giữa H2 và H1 boundary