---
title: Prototype Pollution in Query Builders
type: entity
related: [[NoSQL Injection Bypass Techniques]]
---

Các key prototype pollution được nhắc đến:

- `__proto__`
- `constructor.prototype`

Chúng có thể làm ô nhiễm object prototype được query builders tiêu thụ downstream.