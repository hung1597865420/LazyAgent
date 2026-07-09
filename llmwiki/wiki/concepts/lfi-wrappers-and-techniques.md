---
title: LFI Wrappers and Techniques
type: concept
related: [[Local File Inclusion (LFI)]]
---

LFI thường được khai thác bằng wrapper hoặc kỹ thuật phụ trợ:

- PHP wrappers như `php://filter`, `zip://`, `data://`, `expect://`
- log/session poisoning
- upload temp names
- `/proc/self/environ` và framework caches
- legacy tricks như null-byte truncation và path length truncation

Các kỹ thuật này mở rộng từ đọc file sang thực thi hoặc lộ secrets.