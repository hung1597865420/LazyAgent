---
title: HTTP Fingerprints
type: concept
related: [[Subdomain Takeover]]
---

HTTP fingerprints là các thông báo mặc định của provider khi resource chưa được claim.

Ví dụ:
- GitHub Pages: "There isn't a GitHub Pages site here."
- Fastly: "Fastly error: unknown domain"
- Heroku: "No such app"
- S3 static site: `NoSuchBucket`
- CloudFront: 403/400 với "The request could not be satisfied"
- Azure App Service default 404
- Shopify unavailable page

TLS certificate CN/SAN cũng có thể tiết lộ host mặc định của provider.