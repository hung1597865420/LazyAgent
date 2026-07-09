---
title: Command Injection Evasion
type: entity
related: [[Command Injection]]
---

Các kỹ thuật evasion được nhắc đến:

- `${IFS}`
- `$'\t'`
- `<`
- token splitting như `w'h'o'a'm'i`
- variable building như `a=i;b=d; $a$b`
- base64 stagers
- PowerShell `IEX(...)`

Chúng giúp vượt qua filter hoặc WAF.