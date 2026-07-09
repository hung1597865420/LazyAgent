---
title: Django Settings
type: entity
related: [[DEBUG and Settings Leakage]]
---

Các cấu hình Django quan trọng được nhắc đến trong tài liệu:

- `DEBUG`
- `ALLOWED_HOSTS`
- `SECRET_KEY`
- `SESSION_COOKIE_SECURE`
- `CSRF_USE_SESSIONS`
- `CSRF_TRUSTED_ORIGINS`
- `MEDIA_ROOT`

Các setting này ảnh hưởng trực tiếp đến bảo mật của ứng dụng, đặc biệt là leakage, host header handling, session security và CSRF enforcement.