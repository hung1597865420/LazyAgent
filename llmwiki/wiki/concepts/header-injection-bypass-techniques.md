---
title: Header Injection Bypass Techniques
type: concept
related: [[HTTP Header Injection]]
---

Các kỹ thuật bypass thường gặp:

- URL-encode và double-encode CR/LF
- Mix encodings trong cùng payload
- Unicode newline-equivalent
- Leading/trailing whitespace và tabs
- Header folding / obs-fold
- Duplicate headers
- Method override qua `X-HTTP-Method-Override`, `X-Method-Override`, `X-HTTP-Method`
- Case mangling và null byte truncation

Mục tiêu là vượt qua WAF, filter, hoặc parser mismatch.