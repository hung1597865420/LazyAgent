---
title: JWT Signature Verification
type: concept
related: [[Authentication / JWT / OIDC Attack Surface]]
---

Xác minh chữ ký JWT phải được pin chặt vào thuật toán và key đã biết.

Lỗi phổ biến:
- RS256 → HS256 confusion: đổi `alg` sang HS256 và dùng RSA public key làm HMAC secret nếu thư viện không pin algorithm
- Chấp nhận `alg: none`
- ECDSA malleability hoặc cấu hình verify yếu chấp nhận signature không canonical

Nguyên tắc:
- Không tin `alg` từ token nếu stack không pin thuật toán
- Chỉ chấp nhận thuật toán và key phù hợp với issuer đã cấu hình