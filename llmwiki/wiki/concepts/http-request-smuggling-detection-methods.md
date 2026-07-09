---
title: HTTP Request Smuggling Detection Methods
type: concept
related: [[HTTP Request Smuggling]]
---

Các phương pháp phát hiện request smuggling:

- Timing-based detection
- Differential response detection
- Obfuscation của `Transfer-Encoding`
- HTTP/2-specific detection

Mục tiêu là xác định nơi front-end và back-end disagree về framing.