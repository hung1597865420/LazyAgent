---
title: Open Redirect Encoding Bypasses
type: entity
related: [[Open Redirect Reconnaissance]]
---

Các bypass bằng encoding được nhắc đến:

- double encoding như `%2f%2fevil.com`
- mixed case scheme như `hTtPs://evil.com`
- scheme smuggling như `http:evil.com`
- IP variants: decimal, octal, hex, IPv6 mapped
- user-controlled path bases như `/out?url=/\\evil.com`

Đây là các biến thể để vượt qua kiểm tra URL yếu.