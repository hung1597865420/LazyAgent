---
title: Elasticsearch Query Injection
type: concept
related: [[NoSQL Injection]]
---

Elasticsearch query injection thường xuất hiện trong `query_string` hoặc `simple_query_string` khi input đi thẳng vào Lucene syntax.

Ngoài ra, script injection có thể xảy ra nếu trường `source` của Painless script bị user kiểm soát.