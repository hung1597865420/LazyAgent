---
title: Session Weaknesses
type: concept
related: [[FastAPI Attack Surface]]
---

Session trong FastAPI/Starlette có thể yếu nếu cấu hình không đúng.

Rủi ro chính:
- `SessionMiddleware` dùng `secret_key` yếu
- Session fixation do signing có thể đoán được
- Cookie-based auth nhưng không có CSRF protection

Kiểm tra:
- Đánh giá độ mạnh và bảo mật của `secret_key`
- Xem session có bị cố định qua login hay không
- Kiểm tra cơ chế bảo vệ CSRF cho các endpoint dùng cookie auth

Khuyến nghị:
- Dùng secret key mạnh và bảo vệ tốt
- Rotate session khi đăng nhập
- Không dựa vào cookie auth nếu không có biện pháp chống CSRF