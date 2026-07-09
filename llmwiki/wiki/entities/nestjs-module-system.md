---
title: NestJS Module System
type: entity
related: [[Module Boundary Leaks]]
---

Module system của NestJS gồm:

- `@Module`
- provider scoping: DEFAULT, REQUEST, TRANSIENT
- dynamic modules: `forRoot`, `forRootAsync`
- global modules
- DI container
- provider overrides
- custom providers

Thực thể này quyết định phạm vi truy cập và vòng đời của provider trong ứng dụng.