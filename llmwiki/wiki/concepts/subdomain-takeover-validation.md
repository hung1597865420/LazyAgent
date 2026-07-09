---
title: Subdomain Takeover Validation
type: concept
related: [[Subdomain Takeover Testing Methodology]]
---

Validation cần chứng minh:
- trước và sau khi claim có khác biệt rõ ràng
- content unique được serve qua HTTPS
- có thể dùng DV certificate hoặc CT entry làm evidence
- impact chain như CSP, OAuth, cookie scoping

Cần bằng chứng rằng control đã chuyển sang attacker/defender claim hợp lệ.