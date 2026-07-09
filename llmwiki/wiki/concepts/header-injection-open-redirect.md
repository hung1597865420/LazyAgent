---
title: Open Redirect via Headers
type: concept
related: [[HTTP Header Injection]]
---

Open redirect qua header xảy ra khi `Location`, `Refresh`, `Link`, hoặc `X-Accel-Redirect` nhận giá trị do attacker kiểm soát.

Rủi ro:
- redirect tới domain attacker
- bypass một số filter chỉ kiểm tra `Location`
- lộ internal-only file qua `X-Accel-Redirect`

Nguyên tắc:
- Redirect target phải được allowlist và normalize