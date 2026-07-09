---
title: Server-Side JavaScript Detection
type: entity
related: [[Server-Side JavaScript Injection]]
---

Câu lệnh kiểm tra được nhắc đến:

```javascript
db.adminCommand({getParameter: 1, javascriptEnabled: 1})
```

Dùng để fingerprint trạng thái server-side JavaScript trước khi thử payload.