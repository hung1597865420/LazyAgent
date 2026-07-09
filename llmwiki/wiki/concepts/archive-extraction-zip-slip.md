---
title: Archive Extraction / Zip Slip
type: concept
related: [[Path Traversal / LFI / RFI]]
---

Zip Slip là lỗi khi file trong archive chứa `../` hoặc absolute path làm file được giải nén ra ngoài thư mục đích.

Tác động:
- overwrite config/templates
- drop webshell vào thư mục được serve
- ghi file ngoài target directory

Cần kiểm tra canonicalization và symlink handling trước khi write.