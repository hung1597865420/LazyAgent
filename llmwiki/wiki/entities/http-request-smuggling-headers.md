---
title: HTTP Request Smuggling Headers
type: entity
related: [[HTTP Request Smuggling Parser Differentials]]
---

Các header liên quan đến request smuggling:

- `Content-Length`
- `Transfer-Encoding`
- `Transfer-Encoding: chunked`
- duplicate `Content-Length`
- `content-length` trong HTTP/2
- `transfer-encoding` trong HTTP/2
- `Content-Type: application/x-www-form-urlencoded`
- `X-Forwarded-Host`
- `Host`
- `Upgrade`

Đây là các thực thể framing và routing cần kiểm tra.