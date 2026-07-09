---
title: Signed Blob Bypass
type: entity
related: [[Advanced Deserialization Techniques]]
---

Các yếu tố liên quan đến signed blob bypass:

- HMAC/signing secret yếu
- algorithm confusion
- unsigned code paths
- length extension trên MAC cũ

Đây là các điều kiện có thể cho phép forge serialized payload.