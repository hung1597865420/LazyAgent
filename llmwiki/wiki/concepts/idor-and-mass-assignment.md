---
title: IDOR and Mass Assignment
type: concept
related: [[Django]]
---

IDOR và mass assignment là hai vấn đề rất thường gặp trong Django/DRF khi quyền truy cập và quyền ghi dữ liệu không được giới hạn đúng cách.

Rủi ro chính:
- `get_object()` không lọc theo `request.user`
- `queryset = Model.objects.all()` kết hợp permission yếu
- Serializer dùng `fields = '__all__'` làm lộ hoặc cho phép sửa field nhạy cảm
- Thiếu `read_only_fields` cho `is_staff`, `is_superuser`, `role`, `balance`
- Nested writes có thể cập nhật foreign key xuyên tenant

Cách kiểm tra:
- Đổi ID giữa hai tài khoản trên mọi CRUD route
- Soát serializer để tìm field writable nhạy cảm
- Kiểm tra object-level permission trên cả list, retrieve, update, destroy

Phòng tránh:
- Lọc queryset theo chủ sở hữu hoặc tenant
- Chỉ cho phép field cần thiết
- Đặt `read_only_fields` cho thuộc tính nhạy cảm