---
title: Path Traversal Capability Probes
type: entity
related: [[Path Traversal / LFI / RFI Testing Methodology]]
---

Các probe được nhắc đến:

- baseline traversal như `../../etc/hosts` và `C:\Windows\win.ini`
- encodings như `%2e%2e%2f`, `%252e%252e%252f`, `..%2f`, `..%5c`
- mixed UTF-8 và Unicode dots/slashes
- normalization tests như `..../`, `..\\`, `././`
- absolute path acceptance
- server mismatch như `/static/..;/../etc/passwd` và encoded slashes