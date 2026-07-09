---
title: RSC and Caching Boundaries
type: concept
related: [[Next.js Attack Surface]]
---

React Server Components và cơ chế cache của Next.js có thể làm lộ dữ liệu nếu boundary giữa người dùng không được tách đúng.

Rủi ro:
- User-bound data bị cache mà không gắn identity key
- Personalized content bị phục vụ từ shared cache/CDN
- Thiếu `no-store` trên fetch nhạy cảm
- Flight data chứa field nhạy cảm trong payload streamed
- ISR trả về dữ liệu stale có tính user/tenant-specific

Kiểm tra:
- So sánh ETag, Set-Cookie, và cache behavior giữa các user
- Inspect RSC streamed payloads
- Kiểm tra on-demand revalidation có bị trigger sai hoặc lộ token không

Nguyên tắc:
- Cache phải tôn trọng identity và tenant
- Không cache dữ liệu cá nhân hóa nếu không có key phù hợp