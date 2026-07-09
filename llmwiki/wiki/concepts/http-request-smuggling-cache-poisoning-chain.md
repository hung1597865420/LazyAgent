---
title: Request Reflection and Cache Poisoning Chain
type: concept
type: concept
related: [[HTTP Request Smuggling]]
---

Smuggling có thể được chain với cache poisoning khi prefix bị smuggle chứa header hoặc host làm response cacheable bị sai lệch.

Mục tiêu:
- cache lưu response theo URL nhưng nội dung bị attacker điều khiển
- response poisoned được phục vụ cho nhiều user

Đây là chain giữa request smuggling và cache behavior.