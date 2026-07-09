---
title: Host Header Confusion
type: concept
related: [[HTTP Header Injection]]
---

Host header confusion xảy ra khi backend tin `Host` hoặc `X-Forwarded-Host` để dựng absolute URL, reset link, canonical link, hoặc redirect target.

Rủi ro:
- password reset link trỏ về hạ tầng attacker
- OAuth redirect flow bị lệch host
- precedence giữa `Host` và `X-Forwarded-Host` không nhất quán

Nguyên tắc:
- Host dùng cho routing phải được validate rõ ràng và không lấy từ nguồn không tin cậy