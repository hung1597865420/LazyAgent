---
title: CRUD Generators
type: concept
related: [[NestJS Attack Surface]]
---

Các CRUD generator như `@nestjsx/crud` có thể tạo ra endpoint không thừa hưởng đầy đủ guard thủ công.

Rủi ro:
- Auto-generated endpoints thiếu guard cấu hình tay
- Bulk operations như `createMany`, `updateMany` bỏ qua authorization theo từng entity
- Query params như `filter`, `sort`, `join`, `select` có thể lộ dữ liệu không được phép

Kiểm tra:
- So sánh endpoint sinh tự động với controller thủ công
- Thử bulk operations và query parameter injection

Mục tiêu là đảm bảo generator không mở rộng attack surface ngoài dự kiến.