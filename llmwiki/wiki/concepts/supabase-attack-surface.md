---
title: Supabase Attack Surface
type: concept
related: [[Supabase]]
---

Bề mặt tấn công của Supabase tập trung vào các lớp sau:

- Data access: PostgREST, GraphQL, Realtime
- Storage: buckets, objects, signed URLs
- Authentication: GoTrue JWTs, cookie/session, magic links, OAuth flows
- Server-side: Edge Functions (Deno)

Đây là các khu vực cần map trước khi kiểm thử bảo mật Supabase.