---
title: SSRF Validation
type: concept
related: [[SSRF Testing Methodology]]
---

Validation cần chứng minh:

- outbound server-initiated request
- access tới non-public resources
- credential access hoặc harmless internal read
- reproducibility
- request parameters kiểm soát scheme/host/headers/method/redirect

Cần bằng chứng rõ ràng rằng backend, không phải client, đã thực hiện request.