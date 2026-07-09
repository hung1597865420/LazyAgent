---
title: IDOR via Dependencies
type: concept
related: [[Dependency Injection Gaps]]
---

Trong FastAPI, IDOR có thể xuất hiện khi object ID được lấy từ path/query nhưng không được ràng buộc với người gọi.

Các mẫu lỗi:
- ID trong path/query không được kiểm tra ownership
- Tenant header được tin tưởng thay vì bind với user đã xác thực
- BackgroundTasks xử lý ID mà không re-validate ownership lúc thực thi
- Export/import pipeline rò rỉ dữ liệu cross-tenant

Cách kiểm tra:
- Đổi ID giữa hai tài khoản
- Kiểm tra cross-tenant access
- Xem ownership có được xác minh ở thời điểm xử lý cuối cùng hay không