---
title: Django Attack Surface
type: entity
related: [[Django Security Testing Methodology]]
---

Các thành phần bề mặt tấn công chính của ứng dụng Django/DRF gồm:

- URL routing (`urls.py`)
- Class-based views và function views
- Middleware stack
- ORM: QuerySet filters, raw SQL, `extra()`, `RawSQL`, annotations
- Templates: Django template language, Jinja2 nếu được cấu hình
- Forms, ModelForms, serializers (DRF)
- Session framework và authentication middleware
- Token auth, JWT, OAuth integrations
- Django admin (`/admin/`)
- ASGI/Channels, Daphne, Uvicorn

Thực thể này mô tả các khu vực cần kiểm tra khi đánh giá bảo mật Django.