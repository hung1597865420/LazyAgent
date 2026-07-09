---
title: Protocol Wrappers
type: concept
related: [[XXE]]
---

Một số protocol wrappers mở rộng bề mặt XXE:
- Java: `jar:`, `netdoc:`
- PHP: `php://filter`, `expect://`
- Gopher: raw request crafting cho Redis/FCGI

Các wrapper này có thể biến XML fetch thành file read hoặc SSRF nâng cao.