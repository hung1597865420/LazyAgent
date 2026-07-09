---
title: FastAPI Attack Surface
type: concept
related: [[FastAPI]]
---

Bề mặt tấn công của FastAPI/Starlette tập trung vào các thành phần sau:

- ASGI middlewares: CORS, TrustedHost, ProxyHeaders, Session, exception handlers, lifespan events
- Routers và sub-apps: `APIRouter` prefixes/tags, mounted apps, `include_router`, versioned paths
- Dependency injection: `Depends`, `Security`, `OAuth2PasswordBearer`, `HTTPBearer`, scopes
- Pydantic models: v1/v2, unions/Annotated, custom validators, extra fields policy, coercion
- File operations: `UploadFile`, `File`, `FileResponse`, `StaticFiles`
- Templates: `Jinja2Templates`
- HTTP, WebSocket, SSE/StreamingResponse, BackgroundTasks
- Uvicorn/Gunicorn, reverse proxies/CDN, TLS termination, header trust

Đây là các khu vực cần map trước khi kiểm thử bảo mật.