---
title: CSRF Bypass Techniques
type: concept
related: [[CSRF]]
---

Các kỹ thuật bypass thường gặp:

- SameSite nuance: Lax-by-default, legacy clients bỏ qua SameSite
- Origin/Referer obfuscation: null Origin, `about:blank`, `data:` URLs
- Method override qua `_method` hoặc `X-HTTP-Method-Override`
- Token weaknesses: missing/empty token, token không bind session/user/path, token dùng vô hạn
- Content-Type switching: form, multipart, `text/plain`
- Header manipulation và CORS misconfiguration

Mục tiêu là tìm điều kiện mà request cross-site vẫn được chấp nhận.