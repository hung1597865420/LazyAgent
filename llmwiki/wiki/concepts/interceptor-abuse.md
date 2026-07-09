---
title: Interceptor Abuse
type: concept
related: [[NestJS Attack Surface]]
---

Interceptor trong NestJS có thể làm thay đổi luồng request/response và tạo ra rủi ro bảo mật nếu cấu hình sai.

Các vấn đề chính:
- `CacheInterceptor` không đưa user/tenant vào cache key, dẫn đến cache poisoning hoặc data leak
- Response mapping không đầy đủ, làm lộ field nội bộ
- Logging/timeout interceptors thay đổi hành vi xử lý theo cách khó dự đoán

Cách kiểm tra:
- Gửi request authenticated rồi thử request khác user hoặc unauthenticated để xem cache có bị tái sử dụng không
- So sánh response trước và sau mapping

Nguyên tắc:
- Cache phải phân biệt theo identity và tenant
- Mapping phải loại bỏ field nhạy cảm