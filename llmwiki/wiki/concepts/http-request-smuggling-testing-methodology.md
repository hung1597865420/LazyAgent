---
title: HTTP Request Smuggling Testing Methodology
type: concept
related: [[HTTP Request Smuggling]]
---

Quy trình kiểm thử request smuggling:

1. Map proxy chain
2. Probe CL.TE
3. Probe TE.CL
4. Obfuscate TE header
5. Confirm bằng differential response
6. Attempt bypass exploit
7. Attempt capture
8. Test H2.CL/H2.TE

Mục tiêu là chứng minh desync có thể tạo impact bền vững.