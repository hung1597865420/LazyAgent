---
title: Open Redirect Parser Differentials
type: entity
related: [[Open Redirect Reconnaissance]]
---

Các dạng parser differential được nhắc đến:

- userinfo như `https://trusted.com@evil.com`
- backslash/slashes như `https://trusted.com\\evil.com`, `///evil.com`
- whitespace/control như `http%09://evil.com`
- fragment/query tricks như `trusted.com#@evil.com`
- Unicode/IDNA như punycode, full-width dot, trailing dot

Chúng tạo khác biệt giữa validator và browser.