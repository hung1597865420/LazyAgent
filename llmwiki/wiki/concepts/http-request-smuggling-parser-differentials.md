---
title: HTTP Request Smuggling Parser Differentials
type: concept
related: [[HTTP Request Smuggling]]
---

Parser differentials là các khác biệt trong cách các thành phần mạng diễn giải request.

Các điểm khác biệt chính:
- duplicate `Content-Length`
- `Transfer-Encoding: chunked` khi `Content-Length` cũng tồn tại
- chunk size obfuscation bằng whitespace, tab, case, hoặc invalid extensions

Nguyên tắc:
- Chỉ cần một hop diễn giải khác hop còn lại là có thể tạo desync