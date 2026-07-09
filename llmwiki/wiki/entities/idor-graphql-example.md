---
title: IDOR GraphQL Example
type: entity
related: [[IDOR]]
---

Ví dụ GraphQL trong tài liệu:

```graphql
query IDOR {
  me { id }
  u1: user(id: "VXNlcjo0NTY=") { email billing { last4 } }
  u2: node(id: "VXNlcjo0NTc=") { ... on User { email } }
}
```

Ví dụ này minh họa việc swap node IDs và overfetching qua aliases/fragments.