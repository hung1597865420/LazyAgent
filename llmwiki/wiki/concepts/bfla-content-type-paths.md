---
title: BFLA Content-Type Paths
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Cùng một action có thể đi qua các parser/middleware khác nhau tùy content-type.

Các đường cần thử:
- JSON
- form-urlencoded
- multipart/form-data

Mục tiêu là tìm parser hoặc middleware permissive hơn cho phép action bị chặn ở đường khác.