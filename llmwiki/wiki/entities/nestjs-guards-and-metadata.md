---
title: NestJS Guards and Metadata
type: entity
related: [[Guard Bypass]]
---

Các thực thể guard và metadata quan trọng trong NestJS:

- `@UseGuards`
- `CanActivate`
- execution context: HTTP/WS/RPC
- `Reflector`
- `@SetMetadata`
- `@Public()`
- `@Roles()`
- `@Permissions()`

Chúng quyết định cách quyền được gắn vào controller/method và cách guard đọc metadata để enforce access control.