---
title: Content-Type and Encoding Confusion
type: concept
related: [[HTTP Header Injection]]
---

Content-Type và encoding confusion xảy ra khi attacker chèn header làm client hoặc intermediary hiểu sai loại nội dung.

Rủi ro:
- JSON endpoint bị render như HTML
- UTF-7 legacy XSS
- `Content-Disposition: inline` biến download thành render trong browser
- `Content-Encoding: gzip` giả làm client decode-fail

Nguyên tắc:
- `X-Content-Type-Options: nosniff` là hardening control, nhưng không thay thế cho escaping và normalization