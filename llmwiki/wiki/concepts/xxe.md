---
title: XXE
type: concept
related: [[XXE Attack Surface]]
---

XML External Entity injection là lỗi ở mức parser, có thể dẫn tới:
- đọc file cục bộ
- SSRF tới internal services / metadata
- DoS qua entity expansion
- trong một số stack, code execution qua XInclude/XSLT hoặc wrappers ngôn ngữ

Tài liệu nhấn mạnh rằng mọi XML input phải được coi là untrusted cho tới khi parser được harden đúng cách.