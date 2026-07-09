---
title: Upstream vs Backend Decoding
type: entity
related: [[Path Traversal Bypasses]]
---

Các khác biệt decode được nhắc đến:

- proxies/CDNs decode `%2f` khác backend
- double-decoding
- encoded dots

Sự khác nhau này có thể tạo bypass qua boundary giữa proxy và application.