---
title: CSRF Attack Surface
type: concept
related: [[CSRF]]
---

Bề mặt tấn công CSRF gồm:

- Web apps dùng cookie-based sessions và HTTP auth
- JSON/REST, GraphQL (GET/persisted queries), file upload endpoints
- Login/logout, password/email change, MFA toggles
- OAuth/OIDC authorize, token, logout, disconnect/connect endpoints