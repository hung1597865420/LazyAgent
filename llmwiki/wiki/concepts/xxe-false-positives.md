---
title: XXE False Positives
type: concept
related: [[XXE]]
---

Các trường hợp không nên kết luận XXE:
- DOCTYPE được chấp nhận nhưng entity không resolve
- filter/sandbox chỉ emit literal strings
- mocks/stubs giả lập thành công
- XML chỉ được xử lý client-side

Cần phân biệt parser acceptance với actual IO.