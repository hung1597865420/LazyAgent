---
title: Next.js Path Variants
type: entity
related: [[Middleware Bypass]]
---

Các biến thể path được nhắc đến để kiểm tra normalization:

- `/api/users`
- `/api/users/`
- `/api//users`
- `/api/./users`

Chúng là các thực thể kiểm thử để phát hiện khác biệt giữa middleware và route handler.