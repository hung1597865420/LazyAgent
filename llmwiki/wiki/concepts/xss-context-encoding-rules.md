---
title: Context Encoding Rules
type: concept
related: [[XSS]]
---

Mỗi context cần encoding khác nhau:

- HTML text: encode `< > & " '`
- Attribute value: encode `" ' < > &`, luôn quote attribute
- URL/JS URL: validate scheme, disallow `javascript:` và `data:`
- JS string: escape quotes, backslashes, newlines
- CSS: tránh inject trực tiếp, sanitize property names/values
- SVG/MathML: coi như active content

Sai context encoding là nguyên nhân chính của XSS.