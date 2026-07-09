---
title: BFLA GraphQL Abuse
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

GraphQL có thể bị BFLA ở resolver-level nếu chỉ kiểm tra top-level auth.

Rủi ro:
- Nested mutations hoặc admin fields không được kiểm tra riêng
- Aliases/batching che giấu field đặc quyền
- Persisted queries có thể bypass auth transforms

Nguyên tắc:
- Mỗi mutation/field phải có kiểm tra quyền riêng