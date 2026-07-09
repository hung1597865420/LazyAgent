---
title: Business Logic Refunds and Chargebacks
type: concept
related: [[Business Logic Flaws]]
---

Refunds và chargebacks là mục tiêu giá trị cao vì có thể tạo ra mất tiền trực tiếp.

Rủi ro:
- Double-refund qua UI và support tool
- Refund partials cộng lại vượt captured amount
- Refund sau khi benefits đã consumed

Nguyên tắc:
- Mỗi refund/chargeback phải kiểm tra trạng thái giao dịch và consumption state