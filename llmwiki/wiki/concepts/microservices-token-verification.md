---
title: Microservices Token Verification
type: concept
related: [[JWT Claims Validation]]
---

Trong kiến trúc microservices, mỗi service phải tự xác minh token thay vì tin header do gateway hoặc edge inject.

Rủi ro:
- Service chỉ verify signature nhưng bỏ qua `aud`
- Gateway inject `X-User-Id` và backend tin header hơn token claims
- Async consumers xử lý message với bearer token nhưng không verify lại

Nguyên tắc:
- Mỗi acceptance path phải bind token với service đích
- Không tin header nội bộ nếu không có nguồn gốc xác thực