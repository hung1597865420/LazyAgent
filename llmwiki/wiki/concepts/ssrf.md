---
title: SSRF
type: concept
related: [[SSRF Attack Surface]]
---

Server-Side Request Forgery là lỗi khi server bị lừa thực hiện request tới mạng hoặc dịch vụ mà attacker không truy cập trực tiếp được.

Tài liệu nhấn mạnh các mục tiêu chính:
- cloud metadata endpoints
- internal services
- service meshes
- Kubernetes
- protocol abuse

Một SSRF đơn lẻ có thể dẫn tới credential disclosure, lateral movement, hoặc thậm chí RCE.