---
title: Runtime Divergence
type: concept
related: [[Next.js Attack Surface]]
---

Next.js có thể chạy trên Node hoặc Edge, và cùng một route có thể có hành vi bảo mật khác nhau giữa hai runtime.

Rủi ro:
- Defenses dựa vào Node-only modules không chạy trên Edge
- Header trust khác nhau, đặc biệt với `x-forwarded-*`
- Authorization drift giữa runtime

Kiểm tra:
- So sánh cùng route trên Edge và Node
- Xác minh header handling và auth enforcement

Mục tiêu là đảm bảo bảo vệ nhất quán bất kể runtime.