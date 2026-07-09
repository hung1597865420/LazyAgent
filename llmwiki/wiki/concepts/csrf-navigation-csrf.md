---
title: CSRF Navigation CSRF
type: concept
related: [[CSRF Method and Content-Type Abuse]]
---

Navigation CSRF xảy ra khi trình duyệt tự gửi cookie trong form auto-submit hoặc top-level navigation.

Rủi ro:
- Auto-submitting form tới target origin
- Top-level GET navigation kích hoạt state change
- Các action được gắn với GET callback

Nguyên tắc:
- Không để GET thực hiện thay đổi trạng thái