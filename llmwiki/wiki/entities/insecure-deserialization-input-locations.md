---
title: Insecure Deserialization Input Locations
type: entity
related: [[Insecure Deserialization]]
---

Các vị trí input được nhắc đến:

- Cookies
- session tokens
- hidden form fields
- API parameters như `data`, `state`, `object`
- base64 blobs
- message queues
- WebSocket binary frames
- file uploads
- cache entries
- database columns lưu serialized objects

Đây là các nơi serialized data có thể đi vào application.