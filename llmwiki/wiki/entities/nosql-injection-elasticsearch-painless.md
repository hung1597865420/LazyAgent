---
title: Elasticsearch Painless Script Payload
type: entity
related: [[Elasticsearch Query Injection]]
---

Payload script được nhắc đến:

```json
{"script": {"source": "ctx._source.role = params.r", "params": {"r": "admin"}}}
```

Nếu `source` do user kiểm soát, có thể dẫn đến script injection.