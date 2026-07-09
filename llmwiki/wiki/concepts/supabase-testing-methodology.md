---
title: Supabase Security Testing Methodology
type: concept
related: [[Supabase Attack Surface]]
---

Quy trình kiểm thử bảo mật cho Supabase:

1. Inventory surfaces: REST, Storage, GraphQL, Realtime, Auth, Functions
2. Obtain principals: anon, user A/B, admin; kiểm tra `service_role` leaks
3. Build matrix: Resource × Action × Principal
4. REST vs GraphQL: test cả hai để tìm parity gaps
5. Seed IDs: bắt đầu từ list/search endpoints để thu ID
6. Cross-principal: hoán đổi IDs, tenants, transports giữa principals

Mục tiêu là phát hiện lệch chuẩn giữa RLS, RPC, Storage, Realtime, và Functions.