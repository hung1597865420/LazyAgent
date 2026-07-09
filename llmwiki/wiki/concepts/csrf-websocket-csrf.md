---
title: CSRF WebSocket CSRF
type: concept
related: [[CSRF]]
---

WebSocket CSRF xảy ra vì browser gửi cookies trong handshake.

Rủi ro:
- Cross-site page mở authenticated socket
- Issue actions qua socket nếu không kiểm tra Origin server-side

Nguyên tắc:
- Handshake và message path đều phải có kiểm tra phù hợp