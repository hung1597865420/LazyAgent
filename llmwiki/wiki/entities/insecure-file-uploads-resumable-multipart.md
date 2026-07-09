---
title: Resumable Multipart Uploads
type: entity
related: [[Insecure File Uploads Advanced Techniques]]
---

Các bước/khái niệm resumable multipart được nhắc đến:

- init
- upload/chunk
- complete/finalize
- metadata/headers có thể bị đổi ở bước cuối
- benign chunks rồi swap last chunk

Đây là nơi validation có thể chỉ chạy ở init mà không chạy lại ở finalize.