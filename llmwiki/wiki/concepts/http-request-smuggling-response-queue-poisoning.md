---
title: Response Queue Poisoning
type: concept
related: [[HTTP Request Smuggling]]
---

Response queue poisoning xảy ra trên pipelined connections khi response bị deliver nhầm cho user khác do request/response lệch hàng.

Tác động:
- attacker-controlled content được gửi nhầm
- response của người khác bị lộ
- có thể dẫn đến XSS delivery trong shared connection contexts