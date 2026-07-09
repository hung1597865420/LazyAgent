---
title: SSRF URL Confusion Artifacts
type: entity
related: [[URL Confusion]]
---

Các artifact URL confusion được nhắc đến:

- userinfo `http://internal@attacker/`
- fragment `http://attacker#@internal/`
- scheme-less `//169.254.169.254/`
- trailing dots
- mixed case
- Unicode dot lookalikes