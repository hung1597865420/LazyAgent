---
title: Data Exposure via __NEXT_DATA__
type: concept
related: [[Next.js Attack Surface]]
---

Next.js có thể vô tình đẩy dữ liệu server-fetched vào `__NEXT_DATA__` hoặc props page mà không render ra DOM.

Dữ liệu thường bị lộ:
- Full user objects thay vì chỉ username
- Internal IDs, tokens, admin-only fields
- ORM select-all patterns
- API responses forward thẳng mà không sanitize
- Metadata, cursors, debug info

Kiểm tra:
- Parse `__NEXT_DATA__` và inspect `props.pageProps`
- So sánh dữ liệu giữa user A và user B
- Tìm `_metadata`, `_internal`, `__typename`, nested sensitive objects

Nguyên tắc:
- Chỉ truyền dữ liệu tối thiểu cần thiết cho client