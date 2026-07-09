---
title: Parameter Manipulation
type: concept
related: [[Dependency Injection Gaps]]
---

Một số lỗi trong FastAPI xuất hiện khi tham số được xử lý theo thứ tự ưu tiên không rõ ràng.

Các kỹ thuật kiểm tra:
- Biến thể chữ hoa/thường trong header hoặc cookie names
- Duplicate parameters để khai thác precedence của dependency injection
- Method override qua `X-HTTP-Method-Override` nếu proxy/upstream hỗ trợ

Mục tiêu là tìm ra sự khác biệt giữa cách proxy, framework, và dependency resolver diễn giải cùng một request.