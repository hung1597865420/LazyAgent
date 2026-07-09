---
title: NestJS Config Service
type: entity
related: [[Module Boundary Leaks]]
---

`@nestjs/config` và `ConfigService` là các thực thể cấu hình trong NestJS.

Tài liệu lưu ý rằng secrets từ cấu hình có thể được inject ở nhiều module nếu boundary không chặt, nên cần kiểm soát phạm vi truy cập.