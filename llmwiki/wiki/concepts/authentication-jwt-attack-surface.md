---
title: Authentication / JWT / OIDC Attack Surface
type: concept
related: [[Authentication / JWT / OIDC]]
---

Bề mặt tấn công của JWT/OIDC bao gồm:

- Xác thực web/mobile/API bằng JWT (JWS/JWE) và OIDC/OAuth2
- Access token, ID token, refresh token
- PKCE, device flow, backchannel flow
- Xác thực ở gateway, microservices, và phân phối JWKS

Mục tiêu kiểm thử là phát hiện token forgery, token confusion, cross-service acceptance, và account takeover bền vững.