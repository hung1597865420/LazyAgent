---
title: Cloud Storage Security
type: concept
related: [[Firebase / Firestore Attack Surface]]
---

Cloud Storage trong Firebase có thể lộ file nếu bucket/path public hoặc signed URL được quản lý kém.

Rủi ro:
- Public reads trên bucket hoặc path nhạy cảm
- Signed URL có TTL dài, không kiểm soát `Content-Disposition`, có thể replay giữa tenant
- List operation lộ object keys qua `/o?prefix=`
- Upload HTML/SVG mà thiếu `X-Content-Type-Options: nosniff`

Kiểm tra:
- GET file qua HTTPS không auth
- Generate và reuse signed URL giữa account/path khác nhau
- Kiểm tra list exposure và khả năng script execution từ file upload

Mục tiêu là ngăn đọc/ghi ngoài phạm vi và tránh lộ object enumeration.