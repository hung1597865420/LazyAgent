---
title: JWKS Caching and Rotation
type: concept
related: [[JWT Header Manipulation]]
---

JWKS caching và key rotation có thể tạo ra cửa sổ chấp nhận key cũ hoặc key không mong muốn.

Rủi ro:
- TTL cache quá dài khiến obsolete keys vẫn được chấp nhận
- Race khi rotate key
- Thiếu pinning theo `kid`
- Fallback thử mọi key hoặc không key khi `kid` không tìm thấy
- Dùng chung secret giữa dev/stage/prod hoặc giữa tenant/service

Nguyên tắc:
- Xác minh rotation và cache invalidation
- Không chấp nhận key ngoài whitelist