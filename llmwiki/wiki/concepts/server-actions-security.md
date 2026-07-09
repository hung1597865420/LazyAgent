---
title: Server Actions Security
type: concept
related: [[Next.js Attack Surface]]
---

Server Actions là bề mặt quan trọng trong Next.js vì chúng có thể được gọi ngoài luồng UI thông thường.

Rủi ro chính:
- Gọi action bằng content-type khác với luồng UI dự kiến
- Authorization chỉ dựa vào client state thay vì kiểm tra server-side
- IDOR qua object references trong payload action
- Action ID bị lộ qua source maps hoặc hydration data

Kiểm tra:
- Tìm POST request có `Next-Action` header
- Thử invoke action ngoài UI flow
- Đối chiếu action ID từ source maps và response streams

Mục tiêu là đảm bảo action chỉ thực thi khi có quyền hợp lệ và dữ liệu tham chiếu thuộc về người gọi.