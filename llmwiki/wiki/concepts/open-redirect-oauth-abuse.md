---
title: OAuth/OIDC/SAML Redirect Abuse
type: concept
related: [[Open Redirect]]
---

Open redirect trên domain tin cậy có thể bị dùng để:

- intercept authorization code
- steal tokens
- abuse `redirect_uri`
- abuse `post_logout_redirect_uri`
- abuse `RelayState`

Các flow SSO/OAuth thường là mục tiêu giá trị cao vì liên quan trực tiếp đến phiên đăng nhập và token.