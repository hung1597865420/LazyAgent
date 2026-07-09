---
title: Java SSTI Artifacts
type: entity
related: [[Velocity / Freemarker / Thymeleaf SSTI]]
---

Các artifact Java được nhắc đến:

- `T(java.lang.Runtime).getRuntime().exec('id')`
- `new java.util.Scanner(...).useDelimiter('\\A').next()`
- `T(org.apache.commons.io.IOUtils).toString(...)`
- `freemarker.template.utility.Execute`
- `java.lang.Process`
- `UberspectImpl`
- `SecureUberspector`
- `$class`