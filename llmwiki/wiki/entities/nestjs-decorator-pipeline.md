---
title: NestJS Decorator Pipeline
type: entity
related: [[NestJS Attack Surface]]
---

Decorator pipeline trong NestJS gồm các thành phần:

- Guards: `@UseGuards`, `CanActivate`, execution context, `Reflector`
- Pipes: `ValidationPipe`, `ParseIntPipe`, custom pipes
- Interceptors: response mapping, caching, logging, timeout
- Filters: exception filters
- Metadata decorators: `@SetMetadata`, `@Public()`, `@Roles()`, `@Permissions()`

Đây là contract xử lý request/response và quyền truy cập ở mức framework.