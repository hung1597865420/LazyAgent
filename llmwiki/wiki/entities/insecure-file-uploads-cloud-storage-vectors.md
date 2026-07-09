---
title: Cloud Storage Vectors
type: entity
related: [[Insecure File Uploads]]
---

Các vector cloud storage được nhắc đến:

- S3/GCS presigned uploads
- Content-Type / Content-Disposition do attacker kiểm soát
- public-read ACL
- permissive bucket policies
- object key injection
- signed URL reuse
- stale URLs
- serving trực tiếp từ bucket không có attachment/nosniff

Đây là các điểm dễ dẫn đến public exposure hoặc inline execution.