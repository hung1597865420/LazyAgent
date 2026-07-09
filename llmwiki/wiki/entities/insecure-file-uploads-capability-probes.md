---
title: Insecure File Uploads Capability Probes
type: entity
related: [[Insecure File Uploads]]
---

Các probe được nhắc đến:

- small probe files of each claimed type
- JPEG/GIF/PNG magic bytes
- SVG/HTML probe
- archive probe với path traversal entries và symlinks

Mục tiêu là xác định server dựa vào extension, MIME sniffing, hay content inspection.