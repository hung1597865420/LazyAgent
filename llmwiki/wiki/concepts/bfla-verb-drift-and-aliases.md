---
title: BFLA Verb Drift and Aliases
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Verb drift xảy ra khi cùng một hành động được thực hiện qua method hoặc route khác với kiểm tra yếu hơn.

Ví dụ:
- GET gây thay đổi trạng thái
- POST vs PUT vs PATCH có hành vi khác nhau
- `X-HTTP-Method-Override` hoặc `_method`
- Legacy route hoặc alternate endpoint thực hiện cùng action nhưng middleware yếu hơn