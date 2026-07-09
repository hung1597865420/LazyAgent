---
title: FastAPI WebSocket Endpoints
type: entity
related: [[WebSocket Security]]
---

WebSocket endpoints là các route hai chiều trong FastAPI.

Chúng cần kiểm tra:
- authentication theo connection
- origin validation
- authorization theo message
- topic/channel access control

Đây là thực thể quan trọng để đối chiếu với HTTP endpoints tương đương.