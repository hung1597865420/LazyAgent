---
title: SSRF Impact
type: concept
related: [[SSRF]]
---

Tác động của SSRF:

- cloud credential disclosure
- access to internal control panels and data stores
- lateral movement into Kubernetes/service meshes/CI-CD
- RCE qua protocol abuse, Docker daemon access, hoặc scriptable admin interfaces

SSRF có thể mở ra cả credential theft lẫn execution.