---
title: Middleware Bypass
type: concept
related: [[Next.js Attack Surface]]
---

Middleware bypass trong Next.js xảy ra khi request đi qua nhánh xử lý khác với kỳ vọng của middleware hoặc khi header/path được diễn giải khác nhau giữa middleware và route handler.

Các kỹ thuật thường gặp:
- `x-middleware-subrequest` header crafting
- `x-nextjs-data` probing
- Quan sát `307` cùng `x-middleware-rewrite` hoặc `x-nextjs-redirect`
- Path normalization khác nhau: double slashes, trailing slashes, dot segments
- Parameter pollution: duplicate query params hoặc array params

Nguyên tắc kiểm tra:
- So sánh response giữa middleware và handler
- Thử biến thể path và header
- Xác minh middleware có thực sự bảo vệ route cuối cùng hay không