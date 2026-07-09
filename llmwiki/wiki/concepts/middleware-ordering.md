---
title: Middleware Ordering
type: concept
related: [[Django]]
---

Thứ tự middleware trong Django ảnh hưởng trực tiếp đến việc xác thực, CSRF, và xử lý business logic.

Vấn đề thường gặp:
- Auth middleware chạy sau logic nghiệp vụ
- CSRF không được áp dụng đúng cho session-based API
- Middleware stack tạo ra hành vi khác nhau giữa các route

Cách kiểm tra:
- Xác nhận auth được thực thi trước mọi xử lý nhạy cảm
- Kiểm tra các endpoint session-authenticated có đi qua CSRF middleware hay không
- So sánh hành vi giữa view thường, DRF view, và custom middleware

Nguyên tắc:
- Đặt middleware theo đúng thứ tự phụ thuộc
- Không để business logic chạy trước khi xác thực/ủy quyền hoàn tất