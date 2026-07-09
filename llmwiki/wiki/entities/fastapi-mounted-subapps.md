---
title: FastAPI Mounted Sub-Apps
type: entity
related: [[Mounted Apps Security]]
---

Các sub-app được mount trong FastAPI gồm:

- `/admin`
- `/static`
- `/metrics`

Chúng có thể có middleware và auth behavior khác với main app, nên cần được kiểm tra riêng.