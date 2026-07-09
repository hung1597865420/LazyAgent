---
title: SQL Injection False Positives
type: concept
related: [[SQL Injection]]
---

Các trường hợp không nên kết luận là SQLi:

- generic errors không liên quan SQL parsing/constraints
- static response sizes do templating
- delays do network/CPU không liên quan function call
- parameterized queries không có string concatenation

Cần code review hoặc proof of control để xác nhận.