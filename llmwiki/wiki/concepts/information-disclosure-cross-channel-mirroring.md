---
title: Cross-Channel Mirroring
type: concept
related: [[Information Disclosure]]
---

Cross-channel mirroring là tình huống hardening không nhất quán giữa REST, GraphQL, WebSocket, gRPC, SSR, và CSR.

Hệ quả:
- một kênh che field nhưng kênh khác vẫn lộ
- server-rendered page và JSON API có dữ liệu khác nhau

Nguyên tắc:
- phải kiểm tra đồng nhất trên mọi transport và rendering path