---
title: CSRF Testing Methodology
type: concept
related: [[CSRF]]
---

Quy trình kiểm thử CSRF:

1. Inventory tất cả state-changing endpoints
2. Ghi nhận method, content-type, và khả năng đi qua simple request
3. Đánh giá session model: cookies, SameSite, custom headers, tokens
4. Kiểm tra anti-CSRF token và Origin/Referer enforcement
5. Thử preflightless delivery: form POST, text/plain, multipart/form-data
6. Thử top-level GET navigation
7. Xác minh trên nhiều browser/context khác nhau

Mục tiêu là chứng minh request cross-origin có thể gây state change khi thiếu bảo vệ.