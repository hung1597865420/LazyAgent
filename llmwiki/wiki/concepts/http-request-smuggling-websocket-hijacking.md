---
title: WebSocket Handshake Hijacking
type: concept
related: [[HTTP Request Smuggling]]
---

Nếu proxy hỗ trợ WebSocket upgrade, một smuggled `Upgrade` request có thể hijack kết nối WebSocket của user sau.

Rủi ro:
- chiếm socket đã upgrade
- can thiệp vào luồng message của user khác

Nguyên tắc:
- Upgrade path phải được xử lý nhất quán qua toàn bộ proxy chain