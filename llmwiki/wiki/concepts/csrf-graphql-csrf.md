---
title: CSRF GraphQL CSRF
type: concept
related: [[CSRF Method and Content-Type Abuse]]
---

GraphQL có thể bị CSRF nếu query/mutation được phép qua GET hoặc persisted queries.

Rủi ro:
- Top-level navigation với payload đã encode
- Batched operations che giấu mutation trong request tưởng như an toàn

Nguyên tắc:
- Mutation phải không thể thực hiện qua đường request đơn giản không có bảo vệ