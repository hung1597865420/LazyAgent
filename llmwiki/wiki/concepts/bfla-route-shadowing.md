---
title: BFLA Route Shadowing
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Route shadowing xảy ra khi legacy hoặc alternate routes bỏ qua middleware chain mới.

Ví dụ:
- `/admin/v1` vs `/v2/admin`

Nguyên tắc:
- So sánh middleware stack giữa các route để tìm đường kiểm tra yếu hơn