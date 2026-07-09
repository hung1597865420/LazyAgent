---
title: DNS Indicators
type: concept
related: [[Subdomain Takeover]]
---

Các chỉ báo DNS cho takeover:
- CNAME trỏ tới provider domains
- orphaned NS delegations
- MX tới third-party mail providers với domain đã decommission
- TXT/verification artifacts như `asuid`, `_dnsauth`, `_github-pages-challenge`

Đây là tín hiệu cho thấy subdomain có thể còn phụ thuộc vào resource bên ngoài.