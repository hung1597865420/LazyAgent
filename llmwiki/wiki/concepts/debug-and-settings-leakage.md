---
title: DEBUG and Settings Leakage
type: concept
related: [[Django]]
---

Khi `DEBUG=True` hoặc cấu hình sai, Django có thể tiết lộ thông tin nhạy cảm qua trang lỗi và các endpoint tĩnh.

Thông tin có thể lộ:
- `SECRET_KEY`
- Database credentials
- Installed apps
- Stack traces, đường dẫn file, và ORM queries

Dấu hiệu kiểm tra:
- Trang debug màu vàng
- Error page chi tiết bất thường
- `/static/` hoặc response lỗi tiết lộ đường dẫn nội bộ

Khuyến nghị:
- Luôn tắt DEBUG trên môi trường production
- Dùng error page chung chung
- Kiểm tra kỹ cấu hình reverse proxy và static serving