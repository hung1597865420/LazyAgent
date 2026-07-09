---
title: Business Logic Feature Gates and Roles
type: concept
related: [[Business Logic Flaws]]
---

Feature gates và role transitions không được chỉ enforce ở client hoặc edge.

Rủi ro:
- Feature flags chỉ kiểm tra ở client/edge
- Tên flag có thể đoán được hoặc fallback default-enabled
- Role transitions để lại stale capabilities sau downgrade/demotion

Nguyên tắc:
- Gate và role enforcement phải nằm ở core service mutating state