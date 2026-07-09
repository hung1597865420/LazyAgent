---
title: Host Header and Password Reset Poisoning
type: concept
related: [[Django]]
---

Cấu hình host không chặt có thể dẫn đến host header injection và làm sai logic tạo link tuyệt mật như password reset.

Rủi ro chính:
- `ALLOWED_HOSTS = ['*']` hoặc pattern subdomain quá rộng
- Link reset email được dựng từ `Host` header
- Cache poisoning khi cache key không tính host header

Tác động:
- Poisoned reset links
- Người dùng nhận email chứa domain do attacker kiểm soát

Khuyến nghị:
- Giới hạn `ALLOWED_HOSTS` chặt chẽ
- Không tin `Host` header để dựng URL nhạy cảm
- Kiểm tra cache key và reverse proxy behavior