---
title: SSRF Testing Artifacts
type: entity
related: [[SSRF Testing Methodology]]
---

Các artifact cần kiểm tra khi test:

- user-influenced URL/host/path
- OAST DNS/HTTP callbacks
- loopback/RFC1918/link-local/IPv6/hostnames
- gopher/file/dict protocols
- framework/CDN/library parser differences
- redirect behavior
- header/method control
- metadata/kubelet/Redis/FastCGI/Docker/Vault/internal admin panels