---
title: FastAPI BackgroundTasks
type: entity
related: [[IDOR via Dependencies]]
---

`BackgroundTasks` là cơ chế chạy tác vụ sau response trong FastAPI.

Tài liệu lưu ý rằng các task này có thể thao tác trên ID mà không re-validate ownership tại thời điểm thực thi, dẫn đến IDOR hoặc cross-tenant leaks.