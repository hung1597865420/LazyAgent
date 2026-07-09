---
title: Firebase Rules Snippets
type: entity
related: [[Firestore Rules Security]]
---

Các snippet rules được nhắc đến trong tài liệu:

- `request.auth != null`
- `request.resource.data.keys().hasOnly([...])`
- `resource.data.ownerId == request.auth.uid`
- `request.resource.data.ownerId == request.auth.uid`
- `exists(/databases/(default)/documents/orgs/$(org)/members/$(request.auth.uid))`

Đây là các biểu thức rules quan trọng để audit và so sánh với logic ứng dụng.