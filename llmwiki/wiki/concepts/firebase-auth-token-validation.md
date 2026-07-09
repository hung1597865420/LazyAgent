---
title: Firebase Auth Token Validation
type: concept
related: [[Cloud Functions Trust Boundaries]]
---

ID token của Firebase phải được xác minh chặt chẽ trước khi tin dùng.

Yêu cầu xác minh:
- Issuer (`accounts.google.com` hoặc `securetoken.google.com/<project>`)
- Audience (`<project>` hoặc `<app-id>`)
- Signature bằng Google JWKS
- Expiration
- App Check binding nếu được dùng

Lỗi phổ biến:
- Chấp nhận JWT hợp lệ nhưng sai audience/project
- Tin `uid`/account ID từ request body thay vì `context.auth.uid`
- Trộn session cookies và ID tokens nhưng không verify cả hai path tương đương
- Custom claims được copy vào docs rồi app code tin ngược lại

Kiểm tra:
- Replay token giữa môi trường/project
- Gọi function có/không có Authorization để so sánh enforcement