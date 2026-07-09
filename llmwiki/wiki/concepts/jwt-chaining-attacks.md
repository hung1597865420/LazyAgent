---
title: JWT Chaining Attacks
type: concept
related: [[JWT Header Manipulation]]
---

Các tấn công chuỗi thường kết hợp JWT với lỗ hổng khác để đạt account takeover hoặc token minting.

Ví dụ:
- XSS → token theft → replay across services
- SSRF → fetch private JWKS → sign tokens accepted by internal services
- Host header poisoning → OIDC redirect_uri poisoning → code capture
- IDOR trong session/impersonation endpoints → mint token cho user khác

Mục tiêu là chứng minh chuỗi khai thác dẫn đến quyền truy cập bền vững.