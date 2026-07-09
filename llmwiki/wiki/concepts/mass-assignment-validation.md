---
title: Mass Assignment Validation
type: concept
related: [[Mass Assignment Testing Methodology]]
---

Validation cần chứng minh:

- request tối thiểu làm thay đổi persisted state
- before/after evidence rõ ràng
- consistency trên ít nhất hai encodings hoặc channels
- nested/bulk writes có tác động trong child objects hoặc array elements
- impact và reproducibility có thể đo được