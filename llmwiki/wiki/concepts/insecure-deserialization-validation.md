---
title: Insecure Deserialization Validation
type: concept
related: [[Insecure Deserialization Testing Methodology]]
---

Validation cần chứng minh:

- object graph do attacker kiểm soát đi tới dangerous sink
- impact cụ thể như RCE, auth bypass, hoặc privilege manipulation
- payload được encode và inject ở đúng vị trí
- payload thất bại an toàn trên version đã fix

Chỉ error stack trace là chưa đủ để kết luận.