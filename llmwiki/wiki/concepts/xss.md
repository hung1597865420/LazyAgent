---
title: XSS
type: concept
related: [[XSS Attack Surface]]
---

Cross-site scripting là lỗi khi user-influenced string được đưa vào sink mà không được encode/sanitize đúng theo context.

Tài liệu nhấn mạnh rằng context, parser, và framework edges rất phức tạp, nên mọi input phải được coi là untrusted cho tới khi được encode đúng cho sink cụ thể và được bảo vệ bởi runtime policy như CSP hoặc Trusted Types.