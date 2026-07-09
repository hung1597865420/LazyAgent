---
title: Multi-Store NoSQL Injection
type: concept
related: [[NoSQL Injection]]
---

NoSQL injection không chỉ ở MongoDB mà còn có thể xuất hiện ở:

- DynamoDB PartiQL / FilterExpression
- Cassandra CQL
- CouchDB Mango / design docs
- Neo4j Cypher
- Couchbase / DocumentDB / HBase / ScyllaDB / Memcached theo mô hình tương tự

Mỗi store có cú pháp và primitive khác nhau, nhưng cùng root cause là user input điều khiển query structure.