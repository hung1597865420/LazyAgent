---
title: Mobile Token Security
type: concept
related: [[Token Storage and Transport Security]]
---

Trong mobile, token có thể bị lộ qua deep-link, WebView bridge, hoặc lưu trữ không an toàn.

Rủi ro:
- Deep-link/redirect bugs làm lộ code/token
- WebView bridge không an toàn
- Token lưu plaintext trong file, SQLite, Keychain, SharedPrefs
- Backup/adb có thể truy cập dữ liệu

Nguyên tắc:
- Bảo vệ luồng redirect và storage trên thiết bị