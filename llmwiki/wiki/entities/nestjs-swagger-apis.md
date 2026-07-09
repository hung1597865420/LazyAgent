---
title: NestJS Swagger APIs
type: entity
related: [[NestJS Attack Surface]]
---

`@nestjs/swagger` là lớp tạo OpenAPI cho NestJS.

Nó có thể expose:
- DTO schemas
- auth schemes
- paths
- example values
- internal/deprecated routes

Các endpoint production như `/api`, `/api-docs`, `/api-json`, `/swagger` thường được dùng để khám phá attack surface.