---
title: Neo4j Cypher Injection
type: entity
related: [[Neo4j Cypher Injection]]
---

Cypher injection xảy ra khi input được nối vào query thay vì dùng parameter `$param`.

Ví dụ được nhắc đến:

```python
session.run(f"MATCH (u:User {{name: '{name}'}}) RETURN u")
```

Payload có thể làm lệch câu lệnh và UNION sang truy vấn khác.