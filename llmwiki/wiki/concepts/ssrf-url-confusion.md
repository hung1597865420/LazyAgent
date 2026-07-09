---
title: URL Confusion
type: concept
related: [[SSRF]]
---

URL parser differential hoặc URL confusion xảy ra khi checker và fetcher hiểu URL khác nhau.

Các điểm cần test:
- userinfo
- fragments
- scheme-less/relative forms
- trailing dots
- mixed case
- Unicode dot lookalikes

Đây là nguồn bypass phổ biến cho allowlist.