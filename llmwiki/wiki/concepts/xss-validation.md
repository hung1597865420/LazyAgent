---
title: XSS Validation
type: concept
related: [[XSS Testing Methodology]]
---

Validation cần chứng minh:
- payload tối thiểu và sink type rõ ràng
- before/after DOM hoặc network evidence
- cross-browser behavior nếu liên quan
- bypass của sanitizer/CSP/Trusted Types
- impact thực tế như exfiltration, CSRF chain, persistence

Mục tiêu là chứng minh execution và impact, không chỉ alert.