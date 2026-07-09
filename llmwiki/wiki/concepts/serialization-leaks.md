---
title: Serialization Leaks
type: concept
related: [[NestJS Attack Surface]]
---

NestJS có thể rò rỉ dữ liệu khi serialization không được cấu hình đúng.

Rủi ro:
- Thiếu `ClassSerializerInterceptor` toàn cục khiến `@Exclude()` không có tác dụng trong response
- `@Expose()` với groups nhưng groups không được enforce theo request
- Eager-loaded relations từ TypeORM/Prisma làm lộ toàn bộ object graph

Kiểm tra:
- So sánh entity thô với response API
- Xác minh các field như password, internal IDs, metadata không xuất hiện

Mục tiêu là đảm bảo response chỉ chứa dữ liệu đã được phép xuất ra.