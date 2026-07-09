---
title: Subdomain Takeover Testing Methodology
type: concept
related: [[Subdomain Takeover]]
---

Quy trình kiểm thử:
1. Enumerate subdomains
2. Resolve DNS
3. HTTP/TLS probe
4. Fingerprint providers
5. Attempt claim với authorization
6. Validate control

Mục tiêu là xác định subdomain nào còn phụ thuộc vào resource chưa được claim.