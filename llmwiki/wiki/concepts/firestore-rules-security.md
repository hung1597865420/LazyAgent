---
title: Firestore Rules Security
type: concept
related: [[Firebase / Firestore Attack Surface]]
---

Firestore rules không phải là bộ lọc kết quả truy vấn; một query phải có các điều kiện làm cho rule đúng với mọi document trả về.

Các lỗi phổ biến:
- `allow read: if request.auth != null` cho phép mọi user đã đăng nhập đọc toàn bộ dữ liệu
- `allow write: if request.auth != null` cho phép mass write
- Thiếu validate theo field, cho phép thêm `isAdmin`, `role`, `tenantId`
- Dùng `ownerId`/`orgId` do client cung cấp thay vì so với `request.auth.uid`
- Rule list quá rộng ở root collection làm lộ dữ liệu dù per-doc check có tồn tại

Mẫu an toàn:
- Giới hạn field bằng `request.resource.data.keys().hasOnly([...])`
- Ràng buộc ownership bằng `resource.data.ownerId == request.auth.uid`
- Kiểm tra membership bằng `exists(...)`

Kiểm tra:
- So sánh kết quả giữa user A/B trên cùng query
- Thử cross-tenant read và write với `ownerId`/`orgId` giả mạo