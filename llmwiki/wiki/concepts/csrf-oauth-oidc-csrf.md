---
title: CSRF in OAuth/OIDC Flows
type: concept
related: [[CSRF]]
---

OAuth/OIDC endpoints có thể bị CSRF nếu cho phép GET hoặc form POST mà không kiểm tra origin.

Rủi ro:
- `authorize`, `logout` endpoints
- Relaxed SameSite trên top-level navigations
- Open redirect hoặc `redirect_uri` validation lỏng lẻo

Nguyên tắc:
- Kiểm tra origin và redirect URI chặt chẽ