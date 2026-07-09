---
title: Open Redirect Allowlist Mistakes
type: entity
related: [[Open Redirect Allowlist Validation]]
---

Các lỗi allowlist phổ biến:

- substring/regex contains checks
- wildcard quá rộng như `*.trusted.com`
- missing scheme pinning
- case/IDN drift giữa validator và browser

Đây là nguyên nhân khiến domain độc hại lọt qua kiểm tra.