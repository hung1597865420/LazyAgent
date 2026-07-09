---
title: Django Session Cookie Backends
type: entity
related: [[Session Issues]]
---

Tài liệu đề cập đến backend session signed-cookie của Django:

- `django.contrib.sessions.backends.signed_cookies`

Đặc điểm liên quan bảo mật:
- Session được ký bằng `SECRET_KEY`
- Nếu `SECRET_KEY` bị lộ, attacker có thể forge cookie hợp lệ
- Có thể liên quan đến session forgery và các token ký khác

Đây là một thực thể cấu hình backend session cần được xem xét khi đánh giá rủi ro.