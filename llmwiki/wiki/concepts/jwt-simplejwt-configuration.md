---
title: JWT (simplejwt) Configuration
type: concept
related: [[Django]]
---

Django REST Framework thường dùng `djangorestframework-simplejwt` cho xác thực JWT. Cấu hình sai có thể tạo ra lỗ hổng xác thực.

Rủi ro chính:
- Nhầm lẫn RS256 → HS256 nếu không pin chặt thuật toán
- Không blacklist token sau logout
- Không bật refresh token rotation
- Thiếu ràng buộc `user_id` hoặc token state

Kiểm tra:
- Xác nhận thuật toán được cố định đúng theo thiết kế
- Kiểm tra cơ chế logout có vô hiệu hóa token cũ hay không
- Kiểm tra refresh token có được rotate và revoke đúng cách

Mục tiêu là đảm bảo token không thể bị tái sử dụng hoặc giả mạo do cấu hình sai.