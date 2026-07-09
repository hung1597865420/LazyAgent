---
title: Broken Function Level Authorization (BFLA)
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

BFLA là lỗi xác thực theo mức hành động: caller có thể gọi các function, endpoint, mutation, admin tool mà họ không được phép.

Nguyên tắc cốt lõi:
- Phải bind subject × action tại chính service thực thi hành động
- Không được tin UI gates, gateway, hoặc các bước trước đó như là lớp bảo vệ thay thế
- Enforcement phải nhất quán trên mọi transport, role, và message path