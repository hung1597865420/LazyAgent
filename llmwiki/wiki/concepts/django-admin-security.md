---
title: Django Admin Security
type: concept
related: [[Django]]
---

Django admin là bề mặt tấn công quan trọng vì thường có quyền cao và logic riêng biệt với API.

Rủi ro chính:
- `/admin/` dùng mật khẩu yếu hoặc bị brute force
- Override `has_add_permission` / `has_change_permission` có bug logic
- `ModelAdmin` hiển thị field nhạy cảm trong `list_display` hoặc export

Kiểm tra:
- Xác minh admin auth tách biệt với auth API
- Kiểm tra quyền staff/superuser và các override permission
- Rà soát các field được hiển thị hoặc xuất dữ liệu

Nguyên tắc:
- Không giả định API auth áp dụng cho admin
- Hạn chế field nhạy cảm trong admin UI
- Kiểm tra kỹ custom permission logic