---
title: Aggregation Pipeline Injection
type: concept
related: [[NoSQL Injection]]
---

Aggregation pipeline injection xảy ra khi user influence được các stage như `$match`, `$lookup`, `$project`.

Đặc biệt nguy hiểm khi:
- `$lookup.from` có thể bị điều khiển
- pipeline nhận operator payload giống `find()`
- query có thể pivot sang collection khác