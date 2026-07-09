---
title: WebSocket Security
type: concept
related: [[FastAPI Attack Surface]]
---

WebSocket trong FastAPI cần được bảo vệ tương đương HTTP, nhưng thường thiếu kiểm tra theo kết nối hoặc theo message.

Rủi ro:
- Thiếu authentication theo connection
- Cross-origin WebSocket không có origin validation
- Topic/channel IDOR: subscribe vào kênh của người khác
- Chỉ kiểm tra authorization lúc handshake, không kiểm tra lại ở từng message

Kiểm tra:
- So sánh quyền giữa HTTP và WebSocket cho cùng chức năng
- Thử origin khác và kết nối không auth
- Kiểm tra authorization ở từng message nếu có stateful actions