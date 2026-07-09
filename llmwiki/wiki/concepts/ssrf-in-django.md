---
title: SSRF in Django
type: concept
related: [[Django]]
---

SSRF xuất hiện khi ứng dụng server-side fetch URL do người dùng kiểm soát.

Điểm thường gặp:
- `requests.get(user_url)` trong webhook, preview, import feature
- Celery task lấy URL do người dùng nhập
- Redirect chain dẫn tới tài nguyên nội bộ

Cách kiểm tra:
- Thử loopback, metadata IP, và chuỗi redirect
- Xem các tính năng preview/import/webhook có fetch URL hay không

Phòng tránh:
- Whitelist domain hoặc scheme
- Chặn IP nội bộ và metadata endpoints
- Không cho phép server fetch URL tùy ý nếu không có kiểm soát