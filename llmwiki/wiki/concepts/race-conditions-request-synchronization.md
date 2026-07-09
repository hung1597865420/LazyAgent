---
title: Request Synchronization
type: concept
related: [[Race Conditions]]
---

Để khai thác race condition, cần đồng bộ request thật sát:

- HTTP/2 multiplexing
- last-byte synchronization
- connection warming

Mục tiêu là giảm jitter và làm các request chạm vào cùng một race window.