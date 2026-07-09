---
title: JWT / OIDC Endpoints
type: entity
related: [[Authentication / JWT / OIDC Attack Surface]]
---

Các endpoint liên quan đến JWT/OIDC:

- `/.well-known/openid-configuration`
- `/oauth2/.well-known/openid-configuration`
- `/jwks.json`
- rotating key endpoints
- tenant-specific JWKS
- `/authorize`
- `/token`
- `/introspect`
- `/revoke`
- `/logout`
- device code endpoints
- `/login`
- `/callback`
- `/refresh`
- `/me`
- `/session`
- `/impersonate`

Đây là các contract xác thực, cấp token, và quản lý session.