---
title: SSTI Validation
type: concept
related: [[SSTI Testing Methodology]]
---

Validation cần chứng minh:

- hai biểu thức khác nhau cùng evaluate đúng
- object access hoặc runtime reflection
- side effect như DNS lookup, sleep, hoặc file write
- command output, file write, hoặc OAST callback cho RCE
- payload tối giản nhất có thể