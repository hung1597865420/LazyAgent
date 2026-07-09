---
title: SSRF to RCE
type: concept
related: [[RCE]]
---

SSRF có thể dẫn tới RCE khi internal services expose execution primitives.

Các ví dụ được nhắc đến:
- FastCGI / php-fpm
- Redis
- admin interfaces như Jenkins, Spark UI, Jupyter

Mục tiêu là biến khả năng fetch nội bộ thành thực thi lệnh.