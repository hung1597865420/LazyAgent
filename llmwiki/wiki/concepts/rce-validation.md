---
title: RCE Validation
type: concept
related: [[RCE Testing Methodology]]
---

Validation cần chứng minh:

- oracle tối thiểu như DNS/HTTP/timing
- command context như uid, gid, cwd, env
- file write hoặc persistence nếu có
- boundary crossing trong container nếu áp dụng
- PoC nhỏ, reproducible, và portable