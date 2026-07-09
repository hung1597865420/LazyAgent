---
title: SSTI False Positives
type: concept
related: [[Server-Side Template Injection]]
---

Các trường hợp không nên kết luận là SSTI:

- template syntax chỉ reflect literal
- sandboxed environment nhưng không có reachable objects hữu ích
- client-side template engines
- build-time templating không có user input vào build
- output bị HTML-escape che mất evaluation

Cần phân biệt SSTI với XSS và reflection đơn thuần.