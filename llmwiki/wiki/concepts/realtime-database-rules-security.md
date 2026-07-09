---
title: Realtime Database Rules Security
type: concept
related: [[Firebase / Firestore Attack Surface]]
---

Realtime Database thường bị lộ toàn bộ JSON tree nếu rules cấu hình sai.

Rủi ro chính:
- `.read/.write: true` ở node cao
- Chỉ dùng `auth != null` thay vì kiểm tra `auth.uid` và path granular
- Node chứa roles hoặc membership bị ghi bởi người dùng không có quyền

Kiểm tra:
- Truy cập `/.json` với và không có auth
- Thử đọc/ghi các node privilege-bearing như roles, org membership

Nguyên tắc:
- Rules phải bám theo path và identity cụ thể