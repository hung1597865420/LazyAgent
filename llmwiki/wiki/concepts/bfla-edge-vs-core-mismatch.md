---
title: BFLA Edge vs Core Mismatch
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Lỗi mismatch xảy ra khi edge/gateway chặn action nhưng core service vẫn chấp nhận trực tiếp.

Dấu hiệu:
- Có thể gọi internal service qua exposed API route hoặc SSRF
- Header identity do gateway inject ghi đè token claims
- Cần kiểm tra precedence giữa header và token để phát hiện trust sai nguồn