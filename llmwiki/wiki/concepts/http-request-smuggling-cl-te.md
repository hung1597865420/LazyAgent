---
title: CL.TE Request Smuggling
type: concept
related: [[HTTP Request Smuggling Parser Differentials]]
---

CL.TE là biến thể mà front-end dùng `Content-Length`, còn back-end dùng `Transfer-Encoding`.

Cơ chế:
- Front-end đọc số byte theo `Content-Length`
- Back-end đọc đến chunk terminator `0\r\n\r\n`
- Phần còn lại trong socket buffer trở thành request kế tiếp

Đây là một trong các primitive cổ điển nhất của request smuggling.