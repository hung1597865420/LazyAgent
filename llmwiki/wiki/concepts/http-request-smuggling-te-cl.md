---
title: TE.CL Request Smuggling
type: concept
related: [[HTTP Request Smuggling Parser Differentials]]
---

TE.CL là biến thể mà front-end dùng `Transfer-Encoding`, còn back-end dùng `Content-Length`.

Cơ chế:
- Front-end đọc chunked body đến hết
- Back-end chỉ đọc số byte theo `Content-Length`
- Phần dư còn lại trên socket có thể làm lệch request tiếp theo

Biến thể này thường dẫn đến socket poisoning hoặc timeout.