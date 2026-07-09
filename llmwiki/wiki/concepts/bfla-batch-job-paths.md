---
title: BFLA Batch Job Paths
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Các job path như export/import, webhook, queue có thể tạo ra khoảng trống authz.

Rủi ro:
- Tạo job được phép nhưng finalize/approve không re-check actor
- Replay webhook/background task endpoint để thực hiện privileged action

Nguyên tắc:
- Mỗi bước của job lifecycle phải xác minh lại quyền của caller