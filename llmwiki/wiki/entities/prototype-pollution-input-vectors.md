---
title: Prototype Pollution Input Vectors
type: entity
related: [[Prototype Pollution Attack Surface]]
---

Các input vector được nhắc đến:

- JSON request bodies
- query strings
- multipart form fields
- URL-encoded nested objects như `__proto__[key]=value`
- WebSocket messages
- GraphQL variables
- file import formats (JSON, YAML)