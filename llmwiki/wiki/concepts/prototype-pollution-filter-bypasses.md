---
title: Prototype Pollution Filter Bypasses
type: concept
related: [[Prototype Pollution]]
---

Các bypass phổ biến để vượt qua sanitizer:

- Unicode normalization
- nested forms như `constructor.prototype`
- array pollution
- JSON `$` hoặc `.` keys trong một số parser
- pollution trước khi `Object.freeze`

Mục tiêu là vượt qua blocklist hoặc assumptions của parser.