---
title: Supabase RPC Security
type: concept
related: [[PostgREST and REST Abuse]]
---

RPC endpoints trong Supabase map tới SQL functions và có thể bypass RLS nếu dùng sai.

Rủi ro:
- `SECURITY DEFINER` bỏ qua RLS nếu không kiểm tra owner chặt chẽ
- `set search_path` để public làm function resolve object không an toàn
- Tin `user_id`/`tenant_id` từ client thay vì `auth.uid()`

Nguyên tắc:
- Ưu tiên `SECURITY INVOKER` khi phù hợp
- Nếu dùng `SECURITY DEFINER`, phải kiểm tra ownership/tenant trong SQL
- Không tin input client cho quyết định phân quyền