---
title: Supabase Storage Security
type: concept
related: [[Supabase Attack Surface]]
---

Storage của Supabase có thể lộ dữ liệu nếu bucket public, policy lỏng, hoặc signed URL bị tái sử dụng.

Rủi ro:
- Public bucket/path chứa dữ liệu nhạy cảm
- List exposure qua object listing APIs
- Signed URL reuse giữa tenant/path
- Upload HTML/SVG với content-type nguy hiểm
- Path confusion qua mixed case, URL encoding, `..`

Kiểm tra:
- Truy cập object public không auth
- Thử list prefix
- Kiểm tra `X-Content-Type-Options: nosniff` và `Content-Disposition: attachment`
- So sánh normalization giữa client và server