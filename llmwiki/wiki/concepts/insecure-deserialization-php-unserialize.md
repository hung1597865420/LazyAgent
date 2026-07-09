---
title: PHP unserialize()
type: concept
related: [[Insecure Deserialization]]
---

PHP `unserialize()` là nguồn object injection phổ biến.

Điểm chính:
- magic methods như `__wakeup`, `__destruct`, `__toString`, `__call`
- POP chains qua framework classes
- Phar deserialization có thể bị kích hoạt qua file operations với `phar://`

Đây là một trong các bề mặt deserialization nguy hiểm nhất trong PHP.