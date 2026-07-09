---
title: Insecure Deserialization Reconnaissance
type: concept
related: [[Insecure Deserialization]]
---

Reconnaissance cho insecure deserialization tập trung vào:

- magic bytes / base64 signatures
- `Content-Type` bất thường
- framework indicators
- white-box indicators như `readObject`, `unserialize`, `pickle.loads`, `BinaryFormatter`

Mục tiêu là xác định sink và format trước khi thử payload.