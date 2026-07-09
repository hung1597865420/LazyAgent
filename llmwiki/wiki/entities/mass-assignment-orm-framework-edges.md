---
title: ORM Framework Edges
type: entity
related: [[Mass Assignment Advanced Techniques]]
---

Các framework edge cases được nhắc đến:

- Rails: strong parameters, `accepts_nested_attributes_for`
- Laravel: `$fillable`, `$guarded`, `guarded=[]`, casts
- Django REST Framework: writable nested serializer, `read_only`, `extra_kwargs`, partial updates
- Mongoose/Prisma: schema paths, `select:false`, upsert defaults

Đây là nơi mass assignment thường xuất hiện do cấu hình ORM/binder.