---
title: NestJS Attack Surface
type: concept
related: [[NestJS]]
---

Bề mặt tấn công của NestJS tập trung vào các lớp sau:

- Decorator pipeline: guards, pipes, interceptors, filters, metadata
- Module system: boundaries, provider scoping, dynamic modules, DI container
- Controllers và transports: REST, GraphQL, WebSocket, microservices
- Data layer: TypeORM, Prisma, Mongoose
- Auth & config: passport, JWT, session, config, throttling
- API documentation: `@nestjs/swagger`

Đây là các khu vực cần map trước khi kiểm thử bảo mật ứng dụng NestJS.