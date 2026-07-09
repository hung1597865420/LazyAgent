---
title: Cross-Service Races
type: concept
related: [[Race Conditions]]
---

Cross-service race xảy ra khi state đi qua nhiều service, queue, hoặc compensation flow.

Các nguồn lỗi:
- saga timing gaps
- eventual consistency windows
- retry storms
- at-least-once delivery không có idempotent consumers

Các hệ thống phân tán thường dễ bị race hơn workflow đơn lẻ.