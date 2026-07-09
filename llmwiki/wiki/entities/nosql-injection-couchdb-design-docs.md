---
title: CouchDB Design Docs
type: entity
related: [[CouchDB Mango and View Injection]]
---

Các design doc/view fields được nhắc đến:

- `_design`
- `views.<name>.map`
- `function(doc){ emit(doc._id, doc) }`

Nếu user input đi vào design doc, JavaScript sẽ chạy server-side khi query view.