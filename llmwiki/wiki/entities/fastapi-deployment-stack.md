---
title: FastAPI Deployment Stack
type: entity
related: [[Proxy and Host Trust]]
---

Các thành phần triển khai được nhắc đến:

- Uvicorn
- Gunicorn
- reverse proxies/CDN
- TLS termination
- header trust

Chúng ảnh hưởng đến cách app tin tưởng header, IP, host, và scheme từ client/proxy.