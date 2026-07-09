---
title: Mass Assignment Encodings and Channels
type: concept
related: [[Mass Assignment]]
---

Mass assignment cần được kiểm tra trên nhiều encoding/channel khác nhau:

- `application/json`
- `application/x-www-form-urlencoded`
- `multipart/form-data`
- `text/plain`
- GraphQL inputs
- batch/bulk arrays

Nhiều hệ thống chỉ validate một content-type hoặc bỏ qua allowlist ở bulk path.