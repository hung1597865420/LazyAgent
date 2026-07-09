---
title: NextAuth Pitfalls
type: concept
related: [[Next.js Attack Surface]]
---

NextAuth.js có thể bị cấu hình sai ở các điểm xác thực và callback.

Rủi ro chính:
- Thiếu hoặc nới lỏng state/nonce/PKCE theo provider
- Open redirect qua `callbackUrl`
- Allowed hosts cho callback bị scope sai
- JWT audience/issuer không được enforce giữa các route
- Cross-service token reuse
- Session hijacking thông qua callback flow

Kiểm tra:
- Xác minh state, nonce, PKCE được enforce đúng
- Thử callback URL ngoài phạm vi
- So sánh enforcement giữa các route và provider

Mục tiêu là tránh login CSRF, token mix-up, và redirect abuse.