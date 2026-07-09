---
title: GraphQL Variable Injection
type: concept
related: [[NoSQL Injection]]
---

GraphQL variable injection xảy ra khi resolver truyền biến trực tiếp vào NoSQL filter.

Cần đặc biệt chú ý các input type có thể nhận object tùy ý, vì chúng là ứng viên cho operator injection.

Introspection có thể giúp tìm các field nguy hiểm.