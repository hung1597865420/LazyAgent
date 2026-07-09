---
title: JWT Claims Validation
type: concept
related: [[Authentication / JWT / OIDC Attack Surface]]
---

Claims JWT phải được xác minh đầy đủ trước khi dùng để ra quyết định phân quyền.

Các claim quan trọng:
- `iss`
- `aud`
- `azp`
- `sub`
- `scope`
- `exp`
- `nbf`
- `iat`
- `typ`
- `cty`

Lỗi phổ biến:
- Không enforce `iss`/`aud`/`azp`
- Tin `scope`/`roles` hoàn toàn từ token
- Không enforce `exp`/`nbf`/`iat` hoặc cho clock skew quá lớn
- Không enforce `typ`/`cty`, dẫn đến access token vs ID token confusion

Nguyên tắc:
- Claims chỉ có giá trị khi được ràng buộc với issuer, audience, và context của client