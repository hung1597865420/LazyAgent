---
title: Kubernetes SSRF Targets
type: entity
related: [[SSRF High-Value Targets]]
---

Các target Kubernetes được nhắc đến:

- kubelet 10250
- kubelet 10255
- `/pods`
- `/metrics`
- exec/attach endpoints
- `https://kubernetes.default.svc/`
- cluster DNS names như `svc.cluster.local`
- kube-dns
- metrics-server