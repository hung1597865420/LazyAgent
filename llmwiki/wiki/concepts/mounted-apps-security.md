---
title: Mounted Apps Security
type: concept
related: [[FastAPI Attack Surface]]
---

Các mounted sub-app trong FastAPI có thể bỏ qua middleware toàn cục nếu không được cấu hình đúng.

Ví dụ sub-app:
- `/admin`
- `/static`
- `/metrics`

Rủi ro:
- Bypass global middlewares
- Khác biệt enforcement giữa mount và main app

Kiểm tra:
- Xác minh auth và middleware parity trên mọi mount
- So sánh behavior giữa route chính và sub-app