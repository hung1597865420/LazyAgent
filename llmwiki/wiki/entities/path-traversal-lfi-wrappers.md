---
title: LFI Wrappers
type: entity
related: [[LFI Wrappers and Techniques]]
---

Các wrapper được nhắc đến:

- `php://filter/convert.base64-encode/resource=index.php`
- `zip://archive.zip#file.txt`
- `data://text/plain;base64`
- `expect://`

Chúng thường dùng để đọc source hoặc chuyển từ read sang execution.