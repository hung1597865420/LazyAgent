---
title: Supabase Edge Function Runtime
type: entity
related: [[Supabase Edge Functions Security]]
---

Edge Functions của Supabase chạy trên Deno và thường gọi Supabase bằng secrets hoặc `service_role`.

Đây là runtime/server-side contract cần kiểm tra trust boundary, CORS, và SSRF.