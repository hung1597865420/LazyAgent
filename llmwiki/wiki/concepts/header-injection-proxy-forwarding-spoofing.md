---
title: Proxy and Forwarding Header Spoofing
type: concept
related: [[HTTP Header Injection]]
---

Proxy and forwarding header spoofing là việc giả mạo các header forwarding để bypass IP allowlist, rate limit, HTTPS-only checks, hoặc URL rewriting.

Các header thường gặp:
- `X-Forwarded-For`
- `X-Forwarded-Proto`
- `X-Forwarded-Host`
- `X-Real-IP`
- `Client-IP`
- `True-Client-IP`
- `CF-Connecting-IP`
- `Forwarded`
- `X-Original-URL`
- `X-Rewrite-URL`

Nguyên tắc:
- Chỉ tin các header này ở boundary do chính hệ thống kiểm soát