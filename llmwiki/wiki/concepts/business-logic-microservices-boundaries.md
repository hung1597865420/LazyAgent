---
title: Business Logic Microservices Boundaries
type: concept
related: [[Business Logic Flaws]]
---

Ở boundary giữa microservices, các service có thể có giả định khác nhau về cùng một nghiệp vụ.

Rủi ro:
- Một service validate total, service khác tin line items
- Internal services tin X-Role/X-User-Id từ edge không đáng tin
- Partial failure windows giữa phase 1 và phase 2

Nguyên tắc:
- Mỗi service phải re-validate invariants của chính nó