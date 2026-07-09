---
title: Path Traversal / LFI / RFI
type: concept
related: [[Path Traversal Attack Surface]]
---

Path traversal, local file inclusion (LFI), và remote file inclusion (RFI) là các lỗi xử lý đường dẫn và include file không an toàn.

Hệ quả chính:
- sensitive file disclosure
- config/source leakage
- SSRF pivots
- code execution

Nguyên tắc phòng tránh:
- coi mọi path/scheme do user ảnh hưởng là untrusted
- normalize trước khi dùng
- bind vào allowlist hoặc loại bỏ hoàn toàn user control