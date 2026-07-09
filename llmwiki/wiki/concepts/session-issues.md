---
title: Session Issues
type: concept
related: [[Django]]
---

Các vấn đề cấu hình session trong Django có thể dẫn đến chiếm quyền tài khoản hoặc giả mạo phiên làm việc.

Các lỗi chính:
- `SESSION_COOKIE_SECURE=False` trên site HTTPS
- Thiếu `HttpOnly` cho cookie session
- Session fixation nếu session key không được rotate khi đăng nhập
- `SECRET_KEY` bị lộ, đặc biệt nguy hiểm khi dùng `django.contrib.sessions.backends.signed_cookies`

Tác động:
- Kẻ tấn công có thể forge session cookie nếu có `SECRET_KEY`
- Có thể chiếm phiên sau đăng nhập nếu session không được làm mới

Khuyến nghị:
- Bật `Secure` và `HttpOnly` cho cookie
- Rotate session key sau login
- Bảo vệ `SECRET_KEY` như bí mật cấp cao nhất
- Tránh backend session signed-cookie nếu không kiểm soát tốt khóa ký