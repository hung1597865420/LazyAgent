---
title: Open Redirect Allowlist Validation
type: concept
related: [[Open Redirect]]
---

Validation an toàn cho redirect cần:

- dùng một URL parser hiện đại duy nhất
- so sánh exact scheme và hostname sau IDNA canonicalization
- cho phép path prefix rõ ràng nếu cần
- yêu cầu absolute HTTPS
- từ chối protocol-relative URL và scheme lạ

Không nên dùng substring hoặc regex contains để kiểm tra domain.