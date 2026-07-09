---
title: Dependency Injection Gaps
type: concept
related: [[FastAPI Attack Surface]]
---

Trong FastAPI, quyền truy cập thường được gắn qua dependency injection. Lỗi xảy ra khi một route thiếu dependency bảo vệ hoặc dùng dependency sai loại.

Các mẫu lỗi phổ biến:
- Một số route có security dependency, route khác thì không
- Dùng `Depends` thay vì `Security`, dẫn đến bỏ qua enforcement theo scope
- Chỉ kiểm tra token tồn tại mà không verify chữ ký
- `OAuth2PasswordBearer` chỉ trả về chuỗi token, không đồng nghĩa đã xác thực

Nguyên tắc kiểm tra:
- So sánh dependencies ở router-level và route-level
- Xác minh dependency nào thực sự enforce auth, dependency nào chỉ parse input
- Không coi sự hiện diện của token là đã xác thực