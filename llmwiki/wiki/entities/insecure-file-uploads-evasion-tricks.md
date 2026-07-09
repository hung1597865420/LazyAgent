---
title: Evasion Tricks
type: entity
related: [[Insecure File Uploads Bypass Techniques]]
---

Các trick né kiểm tra được nhắc đến:

- double extensions
- mixed case
- hidden dotfiles
- extra dots như `file..png`
- long paths với suffix hợp lệ
- multipart name vs filename vs path discrepancies
- duplicate parameters
- late parameter precedence

Chúng thường dùng để làm validator và backend hiểu khác nhau.