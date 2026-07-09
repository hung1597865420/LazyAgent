---
title: Mass Assignment
type: concept
related: [[Mass Assignment Attack Surface]]
---

Mass assignment là lỗi khi các field do client gửi được bind trực tiếp vào model/DTO mà không có allowlist theo từng field.

Hệ quả thường gặp:
- privilege escalation
- ownership changes
- unauthorized state transitions

Nguyên tắc phòng tránh:
- explicit mapping
- per-field authorization
- coi mọi attribute từ client là untrusted cho đến khi được validate theo allowlist và caller scope