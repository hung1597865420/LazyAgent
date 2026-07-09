---
title: Firebase Bypass Techniques
type: concept
related: [[Firebase / Firestore Attack Surface]]
---

Các kỹ thuật bypass thường dùng trong kiểm thử Firebase:

- Content-type switching: JSON, form, multipart trên onRequest
- Parameter/field pollution: duplicate JSON keys, last-one-wins
- Caching/CDN: Hosting rewrites không key theo Authorization hoặc tenant headers
- Race windows: write rồi read trước khi enforcement nền hoàn tất

Đây là các kỹ thuật để tìm khác biệt giữa code path, parser, và cache boundary.