---
title: Race Conditions Testing Methodology
type: concept
related: [[Race Conditions]]
---

Quy trình kiểm thử:

1. Model invariants
2. Identify reads/writes
3. Baseline
4. Concurrent requests
5. Scale and synchronize
6. Cross-channel
7. Confirm durability

Mục tiêu là chứng minh concurrent requests làm vỡ invariant một cách lặp lại.