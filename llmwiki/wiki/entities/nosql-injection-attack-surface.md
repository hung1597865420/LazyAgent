---
title: NoSQL Injection Attack Surface
type: entity
related: [[NoSQL Injection]]
---

Các input shape và code pattern được nhắc đến:

- JSON body parameters parsed straight into query objects
- form fields với bracket notation như `field[$ne]=`
- URL-encoded JSON trong query strings, headers, cookies
- GraphQL variables đi thẳng vào resolver-level filters
- raw filter dicts/objects từ user input vào `find`/`findOne`/`aggregate`
- string concatenation vào Cypher / CQL / Redis commands
- ODM passthrough như Mongoose, Morphia, PyMongo
- server-side JavaScript surfaces như `$where`, `$function`, `$accumulator`, CouchDB `_design` views