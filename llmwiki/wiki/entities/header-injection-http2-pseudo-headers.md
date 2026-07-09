---
title: HTTP/2 Pseudo-Headers
type: entity
related: [[HTTP/2 Pseudo-Header and Frame Confusion]]
---

Các pseudo-header HTTP/2 được nhắc đến:

- `:method`
- `:path`
- `:authority`
- `:scheme`

Chúng là các thành phần đặc biệt của HTTP/2 và có thể bị mishandle khi downgrade hoặc filter không đồng nhất.