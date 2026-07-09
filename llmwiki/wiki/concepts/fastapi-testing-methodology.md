---
title: FastAPI Security Testing Methodology
type: concept
related: [[FastAPI Attack Surface]]
---

Quy trình kiểm thử bảo mật cho FastAPI/Starlette:

1. Enumerate: lấy OpenAPI và so sánh với 404-fuzzing để tìm endpoint ẩn
2. Matrix testing: test từng route theo unauth/user/admin × HTTP/WebSocket × JSON/form/multipart
3. Dependency analysis: map dependency nào enforce auth, dependency nào chỉ parse input
4. Cross-environment: so sánh dev/stage/prod về middleware và docs exposure
5. Channel consistency: đảm bảo HTTP và WebSocket có authorization tương đương

Mục tiêu là phát hiện sai lệch giữa router, dependency, middleware, và channel.