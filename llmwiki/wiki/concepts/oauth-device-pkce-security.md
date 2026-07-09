---
title: OAuth Device and PKCE Security
type: concept
related: [[Dependency Injection Gaps]]
---

Các flow OAuth/OIDC như device flow và PKCE cần được kiểm tra chặt chẽ trong FastAPI.

Điểm cần xác minh:
- PKCE phải dùng S256 nghiêm ngặt
- `state` và `nonce` phải được enforce đúng
- Không chấp nhận flow rút gọn làm yếu xác thực

Nếu thiếu các ràng buộc này, attacker có thể lợi dụng flow đăng nhập để chiếm quyền hoặc chèn phiên xác thực.