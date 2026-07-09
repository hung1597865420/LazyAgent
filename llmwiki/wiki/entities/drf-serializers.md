---
title: DRF Serializers
type: entity
related: [[IDOR and Mass Assignment]]
---

Serializer trong DRF định nghĩa dữ liệu nào được đọc và ghi qua API.

Các điểm quan trọng:
- `fields = '__all__'` có thể lộ hoặc cho phép sửa field nhạy cảm
- `read_only_fields` cần đặt cho các thuộc tính như `is_staff`, `is_superuser`, `role`, `balance`
- Nested writes có thể cập nhật quan hệ xuyên tenant

Thực thể này là contract dữ liệu của API và là nơi cần audit để tránh mass assignment.