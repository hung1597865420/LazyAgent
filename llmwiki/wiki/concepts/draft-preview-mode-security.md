---
title: Draft and Preview Mode Security
type: concept
related: [[Next.js Attack Surface]]
---

Draft/preview mode trong Next.js có thể bị lộ hoặc bị kích hoạt sai nếu secret URL/cookie không được bảo vệ.

Rủi ro:
- Secret URLs/cookies enabling preview
- Preview secrets lộ trong client bundles hoặc env
- Preview cookies được set từ subdomain hoặc qua open redirect

Kiểm tra:
- Tìm secret preview path trong bundle/env
- Xác minh cookie và URL preview không bị lạm dụng

Mục tiêu là đảm bảo preview chỉ dùng cho người được phép.