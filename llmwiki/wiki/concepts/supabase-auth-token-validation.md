---
title: Supabase Auth and Token Validation
type: concept
related: [[Supabase Attack Surface]]
---

GoTrue phát hành JWT cho Supabase và các token này phải được xác minh đúng trước khi tin dùng.

Yêu cầu xác minh:
- Issuer
- Audience
- Expiration
- Signature
- Tenant context

Lỗi phổ biến:
- Lưu token trong localStorage dẫn đến XSS exfiltration
- Xem `apikey` như identity thay vì project-scoped key
- Expose `service_role` key
- Refresh token quản lý sai làm session kéo dài quá TTL

Kiểm tra:
- Replay token giữa services
- Thử token expired hoặc sai audience
- Xác minh custom endpoints pin issuer/audience