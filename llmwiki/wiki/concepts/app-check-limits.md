---
title: App Check Limits
type: concept
related: [[Firebase Auth Token Validation]]
---

App Check chỉ là lớp attestation, không thay thế authorization.

Điểm cần nhớ:
- REST calls trực tiếp tới googleapis endpoints vẫn có thể thành công nếu có ID token hợp lệ, bất kể App Check
- Có thể reverse engineer mobile client để tái sử dụng luồng ID token mà không cần attestation

Kiểm tra:
- So sánh hành vi SDK và REST khi có/không có App Check headers
- Xác minh App Check không tạo ra quyền truy cập bổ sung

Nguyên tắc:
- App Check chỉ giảm abuse, không phải cơ chế phân quyền