---
title: Rate Limits and Quotas
type: concept
related: [[Race Conditions]]
---

Rate limit hoặc quota chỉ an toàn nếu counter update là atomic và enforcement đủ rộng.

Các lỗi thường gặp:
- per-IP hoặc per-connection enforcement có thể bị bypass
- counter propagation chậm
- sharding không nhất quán

Kẻ tấn công có thể gửi burst trước khi counter cập nhật kịp.