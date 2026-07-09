---
title: BFLA Feature Flag Bypass
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Feature flag bypass xảy ra khi gate chỉ được kiểm tra ở client/UI nhưng backend vẫn cho phép action.

Kiểm tra:
- Bỏ qua button/flag ở UI và gọi backend trực tiếp
- Invoke admin-only mutation qua GraphQL hoặc gRPC dù UI ẩn

Nguyên tắc:
- Feature gate không được thay thế cho authorization ở backend