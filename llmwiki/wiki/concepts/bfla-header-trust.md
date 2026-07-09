---
title: BFLA Header Trust
type: concept
related: [[Broken Function Level Authorization (BFLA)]]
---

Tin vào header do client/proxy cung cấp là nguyên nhân phổ biến của BFLA.

Ví dụ header đáng ngờ:
- `X-User-Id`
- `X-Role`
- `X-Organization`

Kiểm tra precedence bằng cách gửi header mâu thuẫn với token claims để xem nguồn nào được ưu tiên.