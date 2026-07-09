---
title: MongoDB Authentication Bypass
type: concept
related: [[NoSQL Injection]]
---

MongoDB authentication bypass xảy ra khi query login nhận operator object thay vì string thuần.

Ví dụ điển hình:
- `$ne`
- `$gt`
- `$regex`
- `$in`

Kết quả thường là đăng nhập được vào account đầu tiên hoặc bất kỳ account nào khớp điều kiện rộng.