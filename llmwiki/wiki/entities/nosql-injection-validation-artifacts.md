---
title: NoSQL Injection Validation Artifacts
type: entity
related: [[NoSQL Injection Validation]]
---

Các artifact cần có khi validate:

- login succeeds for any/first account
- extracted secret như password hash, reset token, API key
- normal request 401 vs injected request 200
- timing differential với `$where`

Đây là bằng chứng để chứng minh impact thực sự.