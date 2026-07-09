---
title: MIME Magic Polyglots
type: entity
related: [[Insecure File Uploads]]
---

Các kỹ thuật polyglot/mime spoofing được nhắc đến:

- double extensions như `avatar.jpg.php`, `report.pdf.html`
- mixed casing như `.pHp`, `.PhAr`
- valid JPEG header rồi chèn script

Mục tiêu là vượt qua kiểm tra dựa trên extension hoặc MIME yếu.