---
title: Stored XSS Payloads
type: entity
related: [[Insecure File Uploads]]
---

Các payload XSS được nhắc đến:

- SVG với `onload`/`onerror`
- HTML file với `<script>`
- PDF JavaScript
- office macros trong previewers

Chúng nguy hiểm khi được serve inline hoặc bị browser sniff thành scriptable content.