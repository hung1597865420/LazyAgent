---
title: Module Boundary Leaks
type: concept
related: [[NestJS Attack Surface]]
---

Hệ thống module của NestJS có thể rò rỉ quyền truy cập nếu boundary và scope không được thiết kế đúng.

Rủi ro:
- `@Global()` làm provider có sẵn cho mọi module
- Secrets từ `ConfigService` có thể được inject ở nơi không mong muốn
- Request-scoped provider bị cấu hình thành singleton, gây leak context giữa request
- Provider override hoặc custom provider làm lộ service nội bộ

Kiểm tra:
- Xác minh module nào có thể truy cập provider nào
- Kiểm tra scope của provider trong concurrent requests
- Rà soát dynamic modules và global modules

Mục tiêu là ngăn truy cập chéo giữa các module không được phép.