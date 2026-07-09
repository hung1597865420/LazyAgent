---
title: Prototype Pollution Sanitization Bypasses
type: entity
related: [[Prototype Pollution Filter Bypasses]]
---

Các bypass key sanitization được nhắc đến:

- Unicode normalization và fullwidth underscores
- `constructor.prototype`
- `__proto__[0]`
- `[].__proto__`
- JSON `$` hoặc `.` keys

Đây là các biến thể để vượt qua blocklist theo key.