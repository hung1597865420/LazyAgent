---
title: Server-Side Template Injection
type: concept
related: [[SSTI Attack Surface]]
---

SSTI xảy ra khi user input đi vào template engine như syntax thay vì dữ liệu.

Tài liệu nhấn mạnh rằng impact cuối cùng thường là RCE vì template engine được thiết kế để evaluate expression và thường lộ runtime của host language.

Hai bước quan trọng nhất:
- fingerprint engine
- tìm gadget chain phù hợp với engine đó