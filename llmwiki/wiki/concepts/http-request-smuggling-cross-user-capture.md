---
title: Cross-User Request Capture
type: concept
related: [[HTTP Request Smuggling]]
---

Cross-user request capture là khi attacker poison socket của back-end để request của nạn nhân bị hấp thụ vào response của endpoint do attacker kiểm soát.

Hệ quả:
- lộ `Cookie`
- lộ `Authorization`
- lộ request body

Đây là một trong các impact nghiêm trọng nhất của request smuggling.