---
title: Token Storage and Transport Security
type: concept
related: [[Refresh Token and Session Security]]
---

Cách lưu và truyền token ảnh hưởng trực tiếp đến khả năng bị đánh cắp hoặc replay.

Rủi ro:
- Lưu token trong `localStorage` hoặc `sessionStorage` dẫn đến XSS exfiltration
- CORS lỏng với credentialed requests
- Thiếu `Secure`/`HttpOnly`
- Thiếu mTLS hoặc DPoP/`cnf` binding khiến token replay được từ thiết bị khác

Nguyên tắc:
- Ưu tiên transport và storage giảm thiểu khả năng exfiltration
- Ràng buộc token với client/device khi phù hợp