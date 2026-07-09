---
title: SSRF in FastAPI
type: concept
related: [[FastAPI Attack Surface]]
---

SSRF xảy ra khi ứng dụng server-side fetch URL do người dùng kiểm soát.

Điểm thường gặp:
- Imports, previews, webhooks validation
- Library như `httpx` hoặc `requests` với redirect/header forwarding
- Protocol smuggling như `file://`, `ftp://`, gopher-like shims nếu client tùy biến

Cách kiểm tra:
- Thử loopback, RFC1918, IPv6, redirects, DNS rebinding
- Quan sát hành vi redirect và header forwarding

Phòng tránh:
- Whitelist domain/scheme
- Chặn IP nội bộ và metadata endpoints
- Không cho phép fetch URL tùy ý nếu không kiểm soát