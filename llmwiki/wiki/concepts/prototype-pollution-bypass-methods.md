---
title: Prototype Pollution Bypass Methods
type: concept
related: [[Prototype Pollution Filter Bypasses]]
---

Các phương pháp bypass được nhắc đến:

- switch từ `__proto__` sang `constructor[prototype]`
- array notation như `__proto__[key]`
- content-type switching
- split pollution across multiple parameters
- second-order pollution

Chúng giúp vượt qua filter từng phần hoặc merge theo nhiều bước.