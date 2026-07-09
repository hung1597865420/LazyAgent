---
title: Special Contexts
type: concept
related: [[XSS]]
---

Một số bối cảnh đặc biệt cần kiểm tra riêng:

- Email: thường chặn script nhưng có thể cho CSS/remote content
- PDF and Docs: có thể thực thi JS trong annotation/link
- File uploads: SVG/HTML có thể execute nếu serve sai content-type

Các context này thường bị bỏ sót khi chỉ test web page thông thường.