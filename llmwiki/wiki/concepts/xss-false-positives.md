---
title: XSS False Positives
type: concept
related: [[XSS]]
---

Các trường hợp không nên kết luận XSS:
- reflected content đã encode đúng context
- CSP mạnh với nonce/hash và không inline/event handlers
- Trusted Types enforced và DOMPurify strict mode
- scriptable contexts bị vô hiệu hóa

Cần phân biệt reflection an toàn với execution thật.