---
title: Mass Assignment Testing Methodology
type: concept
related: [[Mass Assignment]]
---

Quy trình kiểm thử:

1. Identify endpoints
2. Capture responses
3. Build sensitive-field dictionary
4. Inject candidates
5. Compare state
6. Test variations

Mục tiêu là xác nhận field nhạy cảm có thể làm thay đổi persisted state đối với caller không đặc quyền.