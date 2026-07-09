---
title: SSRF Chaining Attacks
type: concept
related: [[SSRF]]
---

SSRF thường là bước đầu trong chuỗi tấn công:

- metadata creds → cloud API access
- Redis/FCGI/Docker → file write/command execution
- Kubelet/API → token/secret discovery → lateral movement

SSRF hiếm khi là đích cuối; nó thường mở đường cho impact lớn hơn.