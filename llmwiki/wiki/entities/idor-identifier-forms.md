---
title: IDOR Identifier Forms
type: entity
related: [[IDOR]]
---

Các dạng identifier được nhắc đến:

- Integers
- UUID
- ULID
- CUID
- Snowflake
- Slugs
- Composite keys như `{orgId}:{userId}`
- Opaque tokens
- Base64/hex-encoded blobs

Các dạng này đều có thể bị dùng làm object reference trong IDOR.