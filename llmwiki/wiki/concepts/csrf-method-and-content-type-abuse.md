---
title: CSRF Method and Content-Type Abuse
type: concept
related: [[CSRF]]
---

CSRF thường khai thác các method hoặc content-type không gây preflight.

Điểm cần thử:
- GET, HEAD, OPTIONS có thể gây state change nếu server cấu hình sai
- `application/x-www-form-urlencoded`
- `multipart/form-data`
- `text/plain`
- Parser có thể tự-coerce `text/plain` hoặc form body thành JSON
- Method override qua `_method` hoặc `X-HTTP-Method-Override`

Mục tiêu là tìm đường request đơn giản nhưng vẫn thực hiện được hành động nguy hiểm.