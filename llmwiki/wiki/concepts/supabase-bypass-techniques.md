---
title: Supabase Bypass Techniques
type: concept
related: [[Supabase Attack Surface]]
---

Các kỹ thuật bypass thường dùng trong kiểm thử Supabase:

- Content-type switching giữa JSON, form, multipart
- Parameter pollution với duplicate keys
- GraphQL vs REST parity probing
- Race windows giữa write và background enforcement

Đây là các kỹ thuật để tìm khác biệt giữa parser, policy, và transport.