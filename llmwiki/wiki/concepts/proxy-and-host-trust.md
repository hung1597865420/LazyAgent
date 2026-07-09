---
title: Proxy and Host Trust
type: concept
related: [[FastAPI Attack Surface]]
---

Các middleware và cấu hình proxy/host trust có thể bị lạm dụng nếu không có boundary rõ ràng.

Rủi ro chính:
- `ProxyHeadersMiddleware` không có network boundary, cho phép spoof `X-Forwarded-For/Proto`
- Thiếu `TrustedHostMiddleware`, dẫn đến Host header poisoning
- Cache key confusion nếu thiếu `Vary` trên Authorization/Cookie/Tenant

Kiểm tra:
- Thử spoof header qua proxy
- Xác minh absolute URL và password reset link không phụ thuộc Host header không tin cậy
- Kiểm tra cache behavior theo header nhạy cảm