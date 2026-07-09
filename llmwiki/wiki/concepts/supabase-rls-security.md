---
title: Supabase Row Level Security (RLS) Security
type: concept
related: [[Supabase Attack Surface]]
---

Row Level Security là lớp kiểm soát truy cập cốt lõi của Supabase/Postgres. Nếu RLS không bật hoặc policy quá rộng, dữ liệu có thể bị lộ hàng loạt.

Các lỗi phổ biến:
- Policy chỉ kiểm tra `auth.uid()` cho SELECT nhưng quên UPDATE/DELETE/INSERT
- Thiếu ràng buộc tenant (`org_id`/`tenant_id`) dẫn đến cross-tenant access
- Dựa vào cột do client cung cấp như `user_id` thay vì JWT context
- Join phức tạp khiến policy áp dụng sau filter, cho phép suy luận qua counts

Nguyên tắc:
- Bật RLS cho mọi bảng không public
- Policy phải dựa trên `auth.uid()` và tenant context từ server
- Kiểm tra cả read và write paths