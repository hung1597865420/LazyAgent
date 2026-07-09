---
title: HTTP Header Injection
type: concept
related: [[HTTP Header Injection]]
---

HTTP header injection là lỗi khi input do user kiểm soát được đưa vào header ở mức protocol mà không được normalize đúng cách.

Tác động có thể bao gồm:
- response splitting
- cache poisoning
- session fixation
- authentication bypass
- request smuggling

Nguyên tắc cốt lõi:
- Bất kỳ giá trị nào đi vào header đều phải được xem như code-execution-equivalent cho đến khi chứng minh ngược lại
- Không được nối chuỗi trực tiếp input vào header value
- Phải strip CR/LF và escape đúng cách