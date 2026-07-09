---
title: Path Traversal Attack Surface
type: entity
related: [[Path Traversal / LFI / RFI]]
---

Các bề mặt attack surface được nhắc đến:

- `../` traversal
- encoding and normalization gaps
- include server-side files into interpreters/templates
- remote resources via HTTP/FTP/wrappers
- zip/tar extraction paths
- server/proxy normalization mismatches
- OS-specific paths như Windows separators, device names, UNC, NT paths, alternate data streams