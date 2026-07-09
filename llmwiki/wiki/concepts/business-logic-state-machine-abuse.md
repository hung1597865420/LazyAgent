---
title: Business Logic State Machine Abuse
type: concept
related: [[Business Logic Flaws]]
---

State machine abuse xảy ra khi attacker skip, reorder, hoặc replay các bước của workflow để vượt qua preconditions.

Kỹ thuật:
- Bỏ qua bước bằng direct API call
- Replay bước trước với tham số đã đổi
- Split một action bị giới hạn thành nhiều sub-actions để vượt ngưỡng

Nguyên tắc:
- Mỗi transition phải được kiểm tra pre/post-conditions ở server