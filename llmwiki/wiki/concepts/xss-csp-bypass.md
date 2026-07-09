---
title: CSP Bypass
type: concept
related: [[XSS]]
---

CSP bypass tập trung vào các policy yếu hoặc gadget cho phép thực thi script dù có CSP.

Các điểm yếu được nhắc đến:
- thiếu nonce/hash
- wildcard
- cho phép `data:` / `blob:`
- inline events
- JSONP endpoints
- function constructors
- import maps / modulepreload lax policies
- base tag injection
- dynamic module import

Mục tiêu là tìm đường thực thi script hợp lệ dưới policy hiện tại.