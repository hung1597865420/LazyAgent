---
title: Container and Kubernetes Escalation
type: concept
related: [[RCE]]
---

App RCE có thể mở rộng thành container hoặc cluster compromise nếu môi trường có cấu hình yếu.

Các hướng leo thang được nhắc đến:
- Docker socket
- hostPath mounts
- privileged containers
- Kubernetes service account token
- RBAC/API/kubelet access

Cần xác minh boundary crossing sau khi có RCE.