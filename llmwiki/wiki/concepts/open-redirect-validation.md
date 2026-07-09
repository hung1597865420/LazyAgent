---
title: Open Redirect Validation
type: concept
related: [[Open Redirect Testing Methodology]]
---

Validation cần chứng minh:

- URL tối thiểu dẫn tới external domain qua surface vulnerable
- bypass được regex/allowlist bằng canonicalization variants
- multi-hop chỉ hop đầu được validate
- OAuth/SAML flow có thể đưa code hoặc RelayState tới endpoint attacker-controlled