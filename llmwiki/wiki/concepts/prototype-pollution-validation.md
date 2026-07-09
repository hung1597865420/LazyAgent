---
title: Prototype Pollution Validation
type: concept
related: [[Prototype Pollution Testing Methodology]]
---

Validation cần chứng minh:

- property trên `Object.prototype` ảnh hưởng behavior
- security impact như auth bypass, XSS, hoặc command execution
- pollution tồn tại qua request/page lifetime
- exact merge function và input path
- fix bằng null-prototype objects hoặc key blocklists