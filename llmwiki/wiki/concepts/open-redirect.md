---
title: Open Redirect
type: concept
related: [[Open Redirect Attack Surface]]
---

Open redirect là lỗi khi ứng dụng cho phép điều hướng người dùng đến đích do attacker kiểm soát.

Hệ quả chính:
- phishing pivots
- OAuth/OIDC code and token theft
- allowlist bypass
- SSRF chaining khi server-side fetcher follow redirect

Nguyên tắc phòng tránh:
- canonicalize trước khi kiểm tra
- enforce exact allowlists theo scheme, host, và path
- coi mọi redirect target là untrusted