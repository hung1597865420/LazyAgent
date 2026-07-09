---
title: Open Redirect SSRF Chaining
type: concept
related: [[Open Redirect]]
---

Open redirect có thể được chain với server-side fetchers như web previewers hoặc link unfurlers.

Khi fetcher follow 3xx, attacker có thể pivot từ domain được allowlist sang đích nội bộ như:
- `169.254.169.254`
- `localhost`

Đây là một dạng SSRF gián tiếp qua redirect.