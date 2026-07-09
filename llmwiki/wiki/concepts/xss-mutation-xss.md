---
title: Mutation XSS
type: concept
related: [[XSS]]
---

Mutation XSS khai thác việc parser sửa markup theo cách biến nội dung tưởng như an toàn thành code thực thi.

Các ví dụ thường liên quan tới:
- noscript
- malformed tags
- parser repairs
- form/action tricks

Đây là dạng XSS phụ thuộc vào cách browser sửa DOM sau khi parse.