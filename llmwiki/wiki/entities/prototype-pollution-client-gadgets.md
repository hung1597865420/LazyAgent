---
title: Client-Side Prototype Pollution Gadgets
type: entity
related: [[Client-Side Prototype Pollution]]
---

Các gadget effects được nhắc đến:

- auth checks đọc `user.isAdmin`
- DOM sinks như `innerHTML`
- `document.write`
- script loaders
- cookie/session manipulation

Đây là các nơi polluted properties có thể gây ảnh hưởng.