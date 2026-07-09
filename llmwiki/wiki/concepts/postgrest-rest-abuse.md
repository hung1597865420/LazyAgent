---
title: PostgREST and REST Abuse
type: concept
related: [[Supabase Attack Surface]]
---

PostgREST là lớp REST của Supabase cho table CRUD, filters, embeddings, và RPC.

Rủi ro chính:
- Filter abuse với `eq`, `neq`, `lt`, `gt`, `ilike`, `or`, `is`, `in`
- Overfetch qua embed relations như `select=*,profile(*)`
- Search leaks khi `LIKE`/`ILIKE` rộng kết hợp với RLS yếu
- Mass assignment qua PATCH nếu không chặn cột ngoài ý muốn
- IDOR qua query theo `id`, `slug`, `email`

Kiểm tra:
- So sánh kết quả giữa các principal
- Thử query cross-tenant
- Xác minh cột restricted không thể cập nhật