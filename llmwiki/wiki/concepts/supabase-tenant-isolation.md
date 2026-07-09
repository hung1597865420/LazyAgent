---
title: Supabase Tenant Isolation
type: concept
related: [[Supabase Row Level Security (RLS) Security]]
---

Tenant isolation trong Supabase phải dựa trên `tenant_id`/`org_id` lấy từ JWT context hoặc server context, không dựa vào input client.

Kiểm tra:
- Đổi subdomain/header/path tenant selectors nhưng giữ JWT tenant cố định
- Xác minh export/report endpoints chạy dưới scope của caller

Mục tiêu là ngăn cross-tenant access trên mọi data path.