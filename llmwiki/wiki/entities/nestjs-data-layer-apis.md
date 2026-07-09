---
title: NestJS Data Layer APIs
type: entity
related: [[ORM Injection]]
---

Các API data layer được nhắc đến:

- TypeORM: repositories, QueryBuilder, raw queries, relations
- Prisma: `$queryRaw`, `$queryRawUnsafe`
- Mongoose: operator injection, `$where`, `$regex`

Đây là các contract truy vấn dữ liệu cần được kiểm tra để tránh injection và authorization gaps.