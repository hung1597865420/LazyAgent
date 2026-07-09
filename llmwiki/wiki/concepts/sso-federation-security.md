---
title: SSO Federation Security
type: concept
related: [[OIDC Token Confusion]]
---

Federation SSO có thể bị lỗi khi trust giữa IdP và SP không được cấu hình chặt.

Rủi ro:
- Trust giữa nhiều IdP/SP bị cấu hình sai
- Metadata trộn lẫn hoặc key cũ
- Chấp nhận foreign tokens

Nguyên tắc:
- Pin metadata và key đúng issuer
- Xác minh trust boundary giữa các bên