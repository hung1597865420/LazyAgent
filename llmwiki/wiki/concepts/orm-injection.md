---
title: ORM Injection
type: concept
related: [[NestJS Attack Surface]]
---

NestJS có thể bị ORM injection thông qua các lớp truy vấn động của TypeORM, Mongoose, và Prisma.

TypeORM:
- `QueryBuilder` và `.query()` với template literal interpolation
- API cho phép chọn relations qua query params

Mongoose:
- Query operator injection như `$gt`, `$where`, `$regex`

Prisma:
- `$queryRaw`/`$executeRaw` với string interpolation
- `$queryRawUnsafe`

Nguyên tắc kiểm tra:
- Tìm mọi chỗ ghép chuỗi vào query
- Kiểm tra input có thể điều khiển operator hoặc relation loading hay không