---
title: Firestore Query Abuse
type: concept
related: [[Firestore Rules Security]]
---

Firestore queries có thể bị lạm dụng để tìm lỗ hổng rule coverage hoặc bypass các giả định của SDK.

Điểm cần thử:
- Dùng REST thay vì SDK để tránh ràng buộc phía client
- Probe composite index requirements
- Thử `collectionGroup` queries
- Dùng `startAt`, `endAt`, `in`, `array-contains` để kiểm tra biên rule và pagination cursors

Mục tiêu là phát hiện nơi query trả về dữ liệu ngoài phạm vi dự kiến hoặc rule không bao phủ đầy đủ.