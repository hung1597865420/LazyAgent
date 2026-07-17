---
title: CDN Alternate Domains
type: concept
related: [[Subdomain Takeover]]
---

Một số CDN cho phép add victim subdomain làm alternate domain nếu không kiểm tra ownership đủ mạnh.

Các yếu tố liên quan:
- upload TLS cert
- managed cert issuance
- domain binding verification khác nhau theo provider

Đây là bề mặt takeover phổ biến ở CloudFront, Fastly, 9Router CDN, Akamai.