---
title: BFLA WebSocket Abuse
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

WebSocket có thể chỉ auth ở handshake nhưng không kiểm tra per-message.

Rủi ro:
- Sau khi join channel chuẩn, vẫn emit được privileged events
- Các event như `admin:impersonate` cần re-check trên từng message

Nguyên tắc:
- Authorization phải áp dụng cho từng message/event