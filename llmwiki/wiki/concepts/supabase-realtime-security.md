---
title: Supabase Realtime Security
type: concept
related: [[Supabase Attack Surface]]
---

Realtime của Supabase dùng replication subscriptions và broadcast/presence channels, có thể lộ dữ liệu nếu channel guard yếu.

Rủi ro:
- Channel names tiết lộ updates của user khác khi RLS yếu
- Broadcast/presence cho phép join/publish cross-room không auth

Kiểm tra:
- Subscribe vào channel nhạy cảm và so sánh visibility với RLS
- Thử join channel theo `room:<user_id>` hoặc `org:<org_id>`