---
title: Blind SSRF
type: concept
related: [[SSRF]]
---

Blind SSRF là khi không thấy response trực tiếp nhưng vẫn có thể xác nhận egress qua OAST, timing, response size, TLS errors, hoặc ETag differences.

Tài liệu khuyến nghị dùng OAST callback trước, rồi mới map reachability nội bộ.