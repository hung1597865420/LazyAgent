---
title: JWS Edge Cases
type: concept
related: [[JWT Signature Verification]]
---

Một số edge case của JWS có thể làm thư viện verify sai đường xử lý.

Các trường hợp đáng chú ý:
- Unencoded payload với `b64=false` và `crit`
- Nested JWT (JWT-in-JWT) với thứ tự verify sai

Nguyên tắc:
- Kiểm tra thư viện có xử lý đúng các header đặc biệt và thứ tự verify hay không