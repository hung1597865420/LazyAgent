---
title: Redirect Abuse
type: concept
related: [[SSRF]]
---

Redirect abuse xảy ra khi allowlist chỉ áp dụng ở URL ban đầu nhưng request sau redirect đi tới internal host hoặc protocol khác.

Cần kiểm tra:
- single-hop redirect
- multi-hop redirect
- protocol switch qua redirect

Redirect là leverage quan trọng trong SSRF.