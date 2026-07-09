---
title: Rate Limiting
type: concept
related: [[NestJS Attack Surface]]
---

Rate limiting trong NestJS thường dựa trên `@nestjs/throttler`, nhưng có thể bị vô hiệu hóa hoặc cấu hình sai.

Rủi ro:
- `@SkipThrottle()` trên endpoint nhạy cảm như login, password reset, OTP
- Storage in-memory reset khi restart và không chia sẻ giữa nhiều instance
- Sau proxy nếu không `trust proxy`, IP có thể bị gộp sai hoặc spoof được

Kiểm tra:
- Xác minh endpoint nhạy cảm có bị skip throttle không
- Kiểm tra behavior khi chạy nhiều instance hoặc sau restart
- Kiểm tra IP handling qua proxy