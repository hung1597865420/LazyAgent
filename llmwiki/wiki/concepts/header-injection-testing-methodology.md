---
title: Header Injection Testing Methodology
type: concept
related: [[HTTP Header Injection]]
---

Quy trình kiểm thử header injection:

1. Inventory các response header thay đổi theo input
2. Probe CR/LF normalization trên từng source field
3. Test `Host` và `X-Forwarded-Host` trong flow sinh link
4. Probe forwarding headers trên endpoint bị giới hạn IP
5. Test cache key và response content split
6. Test method override
7. Test request smuggling pairs
8. Cross-protocol replay qua HTTP/1.1 và HTTP/2

Mục tiêu là xác minh header do user kiểm soát có thể ảnh hưởng đến protocol behavior.