---
title: FastAPI OpenAPI and Docs Endpoints
type: entity
related: [[FastAPI Attack Surface]]
---

Các endpoint discovery quan trọng trong FastAPI:

- `/openapi.json`
- `/docs`
- `/redoc`
- `/api/openapi.json`
- `/internal/openapi.json`

Chúng cung cấp attack surface map, `securitySchemes`, `scopes`, và `servers`. Các endpoint bị `include_in_schema=False` sẽ không xuất hiện trong schema.