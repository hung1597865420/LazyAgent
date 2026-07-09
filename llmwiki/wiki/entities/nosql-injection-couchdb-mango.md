---
title: CouchDB Mango Selectors
type: entity
related: [[CouchDB Mango and View Injection]]
---

Các selector Mango được nhắc đến:

```json
{"selector": {"username": "admin", "password": {"$gt": ""}}}
{"selector": {"role": {"$regex": "^admin"}}}
```

Mango selector chấp nhận operator payload tương tự MongoDB.