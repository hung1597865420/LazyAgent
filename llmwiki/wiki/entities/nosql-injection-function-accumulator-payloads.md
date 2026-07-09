---
title: $function and $accumulator Payloads
type: entity
related: [[Server-Side JavaScript Injection]]
---

Payload aggregation JS được nhắc đến:

```json
{"$expr": {"$function": {"body": "function(doc){return doc.role == 'admin'}", "args": ["$$ROOT"], "lang": "js"}}}
```

Đây là cách reach server-side JavaScript qua aggregation.