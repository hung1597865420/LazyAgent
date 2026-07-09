---
title: JWT / OIDC Security Testing Methodology
type: concept
related: [[Authentication / JWT / OIDC Attack Surface]]
---

Quy trình kiểm thử JWT/OIDC:

1. Inventory issuers/consumers: IdP, gateway, services, clients
2. Capture tokens: access và ID token cho nhiều role
3. Map verification endpoints: `/.well-known`, `/jwks.json`
4. Build matrix: token type × audience × service
5. Mutate components: headers, claims, signatures
6. Verify enforcement: hệ thống thực sự kiểm tra gì

Mục tiêu là tìm nơi token được chấp nhận sai context hoặc sai loại.