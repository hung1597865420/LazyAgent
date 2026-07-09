---
title: CSRF Session and Cookie Security
type: concept
related: [[CSRF]]
---

Bảo mật session và cookie là nền tảng của phòng thủ CSRF.

Điểm cần kiểm tra:
- `HttpOnly`
- `Secure`
- `SameSite` với các giá trị `Strict`, `Lax`, `None`
- Cookie `Lax` có thể được gửi trong top-level cross-site GET
- `None` yêu cầu `Secure`

Authorization headers hoặc bearer tokens thường ít CSRF-prone hơn cookies.