---
title: CRLF Response Splitting
type: concept
related: [[HTTP Header Injection]]
---

CRLF response splitting xảy ra khi attacker chèn `\r\n\r\n` để kết thúc response hiện tại và tạo response thứ hai.

Hệ quả:
- downstream proxy hoặc cache có thể key theo response đầu nhưng phục vụ response thứ hai
- có thể dẫn đến cache poisoning hoặc header injection lan rộng

Nguyên tắc:
- Không cho phép CR/LF đi vào header value