---
title: SSTI Fingerprinting Probes
type: entity
related: [[Engine Fingerprinting]]
---

Các probe fingerprint được nhắc đến:

- `{{7*7}}`
- `{{7*'7'}}`
- `${7*7}`
- `<%= 7*7 %>`
- `#{7*7}`
- `{{= 7*7 }}`
- `*{...}` for Thymeleaf selection expressions