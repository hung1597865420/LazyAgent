---
title: Cookie and Set-Cookie Manipulation
type: concept
related: [[HTTP Header Injection]]
---

Cookie/Set-Cookie manipulation là việc chèn thuộc tính cookie qua header injection để mở rộng scope hoặc thay đổi hành vi session.

Các kỹ thuật:
- `Domain=.example.com`
- `Path=/`
- `SameSite=None; Secure`
- `Max-Age=999999999`
- `Max-Age=-1`
- cookie tossing bằng cookie cùng tên với session cookie thật

Nguyên tắc:
- Không để user input điều khiển `Set-Cookie` trực tiếp