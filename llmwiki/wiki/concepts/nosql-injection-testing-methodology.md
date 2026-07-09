---
title: NoSQL Injection Testing Methodology
type: concept
related: [[NoSQL Injection]]
---

Quy trình kiểm thử:

1. Identify query-receiving endpoints
2. Determine input format
3. Send error-probing payloads
4. Attempt operator injection
5. Confirm boolean oracle
6. Extract data blindly
7. Test `$where`
8. Probe aggregation endpoints
9. Test non-MongoDB stores
10. Test GraphQL resolvers

Mục tiêu là xác nhận input có thể thay đổi cấu trúc truy vấn hay không.