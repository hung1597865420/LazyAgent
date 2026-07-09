---
title: CSRF Exposure
type: concept
related: [[Session Weaknesses]]
---

FastAPI/Starlette không có CSRF built-in như một số framework khác, nên các endpoint dùng cookie auth dễ bị bỏ sót.

Rủi ro:
- Cookie-based auth nhưng không có origin validation
- Thiếu `SameSite` cho cookie

Kiểm tra:
- Gửi request cross-origin với cookie phiên
- Xác minh có cơ chế chặn CSRF hoặc origin check hay không

Nguyên tắc:
- Nếu dùng cookie auth, phải bổ sung biện pháp chống CSRF
- Đặt `SameSite` phù hợp và kiểm tra origin