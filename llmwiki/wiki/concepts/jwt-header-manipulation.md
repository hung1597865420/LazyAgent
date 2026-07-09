---
title: JWT Header Manipulation
type: concept
related: [[JWT Signature Verification]]
---

Các header JWT có thể bị lạm dụng để điều khiển key selection hoặc khiến server fetch key từ nguồn attacker-controlled.

Kỹ thuật:
- `kid` injection qua path traversal, SQL/command/template injection, hoặc trỏ tới file world-readable
- `jku`/`x5u` abuse để server fetch JWKS/X509 chain từ host của attacker
- `jwk` header injection để nhúng key trực tiếp trong token
- SSRF qua remote key fetch

Nguyên tắc:
- Pin/whitelist nguồn key
- Không tin inline JWK nếu không được phép
- Không để lookup key phụ thuộc vào input không kiểm soát