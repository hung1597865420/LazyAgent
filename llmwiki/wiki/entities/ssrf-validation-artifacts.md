---
title: SSRF Validation Artifacts
type: entity
related: [[SSRF Validation]]
---

Các artifact cần có khi validate:

- outbound server-initiated request
- internal-only response differences
- non-public resource access
- short-lived token hoặc harmless internal read
- reproducible request parameters
- scheme/host/headers/method/redirect control