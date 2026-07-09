---
title: DynamoDB PartiQL Injection
type: entity
related: [[DynamoDB FilterExpression Injection]]
---

Ví dụ PartiQL được nhắc đến:

```sql
SELECT * FROM Users WHERE username = 'x' OR '1'='1
```

Đây là dạng injection khi query string được nối trực tiếp thay vì dùng binding an toàn.