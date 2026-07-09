---
title: SSRF False Positives
type: concept
related: [[SSRF]]
---

Các trường hợp không nên kết luận là SSRF:

- client-side fetches בלבד
- strict allowlists với DNS pinning và không follow redirect
- mocks/simulators trả canned responses
- blocked egress với lỗi đồng nhất
- OAST callback do máy tester hoặc browser tạo ra, không phải backend