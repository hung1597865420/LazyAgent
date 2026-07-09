---
title: DRF Permission Classes
type: entity
related: [[Permission Class Gaps]]
---

`permission_classes` là cơ chế kiểm soát truy cập của Django REST Framework theo từng view hoặc ViewSet.

Liên quan trong tài liệu:
- Có thể bị thiếu ở một số action như `retrieve`, `update`, `destroy`
- `@api_view` có thể kế thừa default permissive settings nếu không khai báo rõ
- Cần kết hợp với object-level checks để tránh IDOR

Thực thể này đại diện cho contract quyền truy cập của API routes trong DRF.