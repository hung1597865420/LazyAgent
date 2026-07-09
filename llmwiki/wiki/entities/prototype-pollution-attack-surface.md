---
title: Prototype Pollution Attack Surface
type: entity
related: [[Prototype Pollution]]
---

Các bề mặt attack surface được nhắc đến:

- JavaScript/TypeScript browser và Node.js
- JSON parsers giữ lại `__proto__`, `constructor`, `prototype`
- server-side template engines
- config merge utilities
- JSON request bodies
- query strings
- multipart form fields
- WebSocket messages
- GraphQL variables
- file import formats như JSON/YAML