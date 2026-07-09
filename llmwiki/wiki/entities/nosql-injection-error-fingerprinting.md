---
title: Error Fingerprinting
type: entity
related: [[NoSQL Injection Reconnaissance]]
---

Các tín hiệu lỗi được nhắc đến:

- malformed JSON operator objects
- `MongoError`
- `CastError`
- `ValidationError`
- stack traces revealing collection names, field names, driver version

Chúng giúp xác định backend và khả năng operator injection.