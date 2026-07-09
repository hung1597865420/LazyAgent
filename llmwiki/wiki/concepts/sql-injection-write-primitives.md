---
title: SQL Injection Write Primitives
type: concept
related: [[SQL Injection]]
---

Write primitives là các trường hợp SQLi không chỉ đọc dữ liệu mà còn sửa state.

Ví dụ:
- auth bypass bằng tautology/subselect
- privilege changes qua UPDATE
- file write
- job/proc abuse

Đây là nhóm impact cao vì có thể thay đổi dữ liệu hoặc hành vi hệ thống.