---
title: Supabase Edge Functions Security
type: concept
related: [[Supabase Attack Surface]]
---

Edge Functions của Supabase chạy trên Deno và thường dùng `service_role` để gọi Supabase.

Rủi ro:
- Tin `Authorization`/`apikey` headers mà không verify JWT với issuer/audience
- CORS wildcard với credentials
- Reflect Authorization trong response
- SSRF qua fetch tới internal endpoints
- Secrets lộ qua error traces hoặc logs

Kiểm tra:
- Gọi function có/không có Authorization
- Thử payload với foreign resource IDs
- Kiểm tra khả năng reach metadata/internal endpoints