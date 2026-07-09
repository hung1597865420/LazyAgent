---
title: Distributed Locks
type: concept
related: [[Race Conditions]]
---

Distributed lock chỉ an toàn nếu có cơ chế đảm bảo một winner duy nhất.

Các lỗi phổ biến:
- Redis lock không có NX/EX hoặc fencing tokens
- lock lưu trong memory trên một node
- bypass bằng cách hit node/region khác

Lock yếu có thể cho nhiều request cùng thắng.