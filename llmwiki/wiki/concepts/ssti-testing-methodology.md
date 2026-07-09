---
title: SSTI Testing Methodology
type: concept
related: [[Server-Side Template Injection]]
---

Quy trình kiểm thử:

1. Find templated input
2. Fingerprint the engine
3. Confirm evaluation, not reflection
4. Probe sandbox state
5. Enumerate gadgets
6. Reach RCE
7. Validate side effects

Mục tiêu là chứng minh input được evaluate trên server, không chỉ reflect.