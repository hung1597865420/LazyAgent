---
title: Validation Gaps
type: entity
related: [[Insecure File Uploads Bypass Techniques]]
---

Các gap validation được nhắc đến:

- client-side only checks
- tin vào browser-provided MIME/JS
- trust multipart boundary part headers
- extension allowlists không có server-side inspection

Đây là các lỗi thiết kế phổ biến trong upload validation.