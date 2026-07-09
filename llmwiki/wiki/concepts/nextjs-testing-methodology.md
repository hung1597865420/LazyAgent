---
title: Next.js Security Testing Methodology
type: concept
related: [[Next.js Attack Surface]]
---

Quy trình kiểm thử bảo mật cho Next.js:

1. Enumerate: dùng build manifest, source maps, sitemap/robots để map route
2. Runtime matrix: test từng route trên Edge và Node
3. Role matrix: test unauth/user/admin trên SSR, API routes, Route Handlers, Server Actions
4. Cache probing: kiểm tra cache có tôn trọng identity hay không
5. Middleware validation: thử path variants và header manipulation
6. Cross-router: so sánh authorization giữa App Router và Pages Router

Mục tiêu là phát hiện lệch chuẩn giữa router, runtime, cache, và middleware.