---
title: CSRF Misconfiguration
type: concept
related: [[Django]]
---

CSRF trong Django thường được bảo vệ tốt bởi middleware, nhưng có thể bị vô hiệu hóa hoặc cấu hình sai trong các endpoint dùng session authentication.

Các lỗi phổ biến:
- `@csrf_exempt` trên view thay đổi trạng thái
- DRF session auth nhưng không enforce CSRF cho unsafe methods
- `CSRF_USE_SESSIONS` hoặc trusted origins cấu hình sai
- `CSRF_TRUSTED_ORIGINS` quá rộng

Cách kiểm tra:
- Gửi cross-origin POST với cookie phiên của nạn nhân
- Kiểm tra JSON endpoint dùng session auth có chặn CSRF hay không
- Xem các view browsable API hoặc `?format=` có đi qua nhánh xử lý khác không

Khuyến nghị:
- Không exempt CSRF cho endpoint state-changing
- Giới hạn trusted origins chặt chẽ
- Đảm bảo CSRF middleware hoạt động đúng với session-authenticated endpoints