---
title: Content-Type Switching
type: concept
related: [[Pydantic Exploitation]]
---

FastAPI có thể xử lý khác nhau tùy theo `Content-Type`, dẫn đến parser differentials.

Các kiểu thường cần thử:
- `application/json`
- `application/x-www-form-urlencoded`
- `multipart/form-data`

Rủi ro:
- Mỗi content type đi qua validator hoặc code path khác nhau
- Có thể làm lộ bug ở một parser nhưng không ở parser khác

Cách kiểm tra:
- Gửi cùng một payload qua nhiều content type
- So sánh response, validation, và side effects

Đây là kỹ thuật quan trọng để phát hiện khác biệt xử lý đầu vào.