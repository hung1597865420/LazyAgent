---
title: Atomicity Gaps
type: concept
related: [[Race Conditions]]
---

Atomicity gap xuất hiện khi một workflow nhiều bước không được thực hiện như một đơn vị nguyên tử.

Ví dụ:
- lost update trong read-modify-write
- partial two-phase workflow
- unique check ngoài unique index/upsert

Khi có gap, concurrent requests có thể tạo duplicate hoặc sai state.