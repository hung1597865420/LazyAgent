---
title: Client-Side XSS and Hydration Mismatches
type: concept
related: [[Next.js Attack Surface]]
---

Next.js client-side rendering và hydration có thể tạo ra XSS nếu dữ liệu không tin cậy đi vào DOM hoặc render khác nhau giữa server và client.

Rủi ro:
- `dangerouslySetInnerHTML`
- Markdown renderers
- User-controlled `href`/`src`
- CSP/Trusted Types coverage không đầy đủ
- Hydration mismatch tạo gadget-based XSS

Kiểm tra:
- Rà soát các điểm render HTML thô
- So sánh server render và client render
- Xác minh CSP và Trusted Types

Nguyên tắc:
- Không render HTML không tin cậy trực tiếp
- Giảm khác biệt giữa SSR và CSR