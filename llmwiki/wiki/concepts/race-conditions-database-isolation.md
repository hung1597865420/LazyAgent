---
title: Database Isolation
type: concept
related: [[Race Conditions]]
---

Race condition có thể khai thác các anomaly của isolation level hoặc lock granularity.

Các vấn đề được nhắc đến:
- READ COMMITTED
- REPEATABLE READ anomalies
- phantoms
- non-serializable sequences
- row vs table lock
- application locks chỉ giữ trong-process