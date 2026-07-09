---
title: DRF Filter Backend Safety
type: concept
related: [[Django]]
---

Các filter backend của DRF có thể trở thành nguồn lỗi nếu cho phép người dùng điều khiển trường lọc hoặc sắp xếp mà không có whitelist.

Rủi ro chính:
- `django-filter` lộ các field không mong muốn qua query params
- Ordering injection qua `?ordering=` nếu không giới hạn danh sách field hợp lệ
- Search/filter endpoint vô tình cho phép truy cập dữ liệu ngoài phạm vi dự kiến

Cách kiểm tra:
- Xem field nào được expose qua query string
- Thử các tham số như `ordering` với field ngoài whitelist
- Kiểm tra các filter liên quan đến tenant, ownership, hoặc dữ liệu nhạy cảm

Nguyên tắc:
- Whitelist field lọc và field sắp xếp
- Không để client điều khiển trực tiếp tên cột nội bộ
- Kết hợp filter với object-level permission