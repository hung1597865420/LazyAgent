---
title: CSRF CORS Misconfiguration
type: concept
related: [[CSRF]]
---

CORS không phải là biện pháp thay thế cho CSRF protection.

Rủi ro:
- `Access-Control-Allow-Origin` quá rộng
- `Access-Control-Allow-Credentials` kết hợp với origin lỏng lẻo
- Khác biệt CORS giữa từng endpoint
- Preflight và simple request có hành vi khác nhau

CORS sai cấu hình có thể biến CSRF thành data exfiltration.