---
title: Django Security Testing Methodology
type: concept
related: [[Django]]
---

Đây là quy trình kiểm thử bảo mật tổng quát cho ứng dụng Django và Django REST Framework.

Các bước chính:
1. Map surface: URLs, schema DRF, admin, static/media paths
2. Auth matrix: kiểm tra unauthenticated/user/staff cho từng endpoint và method
3. Object ownership: đổi ID giữa hai tài khoản trên mọi CRUD route
4. Serializer audit: tìm field writable nhạy cảm và nested relations
5. Middleware order: xác nhận auth chạy trước business logic và CSRF trên session APIs
6. Channel parity: đảm bảo WebSocket có authorization tương đương REST
7. Settings review: DEBUG, ALLOWED_HOSTS, SECRET_KEY, session/cookie flags

Mục tiêu là phát hiện lỗi ở mức route, object, serializer, và cấu hình triển khai thay vì chỉ kiểm tra xác thực bề mặt.