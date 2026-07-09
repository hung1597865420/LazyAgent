---
title: Cloud Functions Trust Boundaries
type: concept
related: [[Firebase / Firestore Attack Surface]]
---

Cloud Functions có hai kiểu chính với mức trust khác nhau:

- `onCall`: nhận `context.auth` tự động
- `onRequest`: phải tự verify ID token

Rủi ro:
- Tin `uid`/`orgId` từ body thay vì `context.auth`
- Parse token thủ công nhưng thiếu `aud`/`iss`
- CORS quá rộng cho credentialed cross-origin requests
- Trigger `onCreate`/`onWrite` cấp role dựa trên document content do client kiểm soát
- Admin SDK bypass rules, nên ownership/tenant checks phải nằm trong code

Kiểm tra:
- So sánh quyết định auth giữa onCall và onRequest
- Tạo document crafted để kích hoạt trigger
- Thử SSRF từ function tới metadata/project endpoints