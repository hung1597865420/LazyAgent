---
title: Cassandra CQL Injection
type: entity
related: [[Cassandra CQL Injection]]
---

Các mẫu CQL injection được nhắc đến:

- `' OR '1'='1' ALLOW FILTERING --`
- `'x' OR token(username) > token('a') ALLOW FILTERING --`

CQL có hình dạng giống SQL nên dễ bị injection nếu nối chuỗi.