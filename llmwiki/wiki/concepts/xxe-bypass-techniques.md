---
title: XXE Bypass Techniques
type: concept
related: [[XXE]]
---

Các bypass techniques được nhắc đến:
- UTF-16 / UTF-7 declarations
- mixed newlines
- CDATA và comments
- PUBLIC vs SYSTEM
- mixed case DOCTYPE
- internal vs external subsets
- multi-DOCTYPE edge handling
- pivot giữa filesystem và network tùy control bị chặn

Mục tiêu là vượt qua filter hoặc parser hardening không đầy đủ.