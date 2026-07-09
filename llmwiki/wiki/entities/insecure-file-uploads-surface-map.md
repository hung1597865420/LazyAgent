---
title: Insecure File Uploads Surface Map
type: entity
related: [[Insecure File Uploads Testing Methodology]]
---

Các điểm cần map trong pipeline:

- endpoints/fields: upload, file, avatar, image, attachment, import, media, document, template
- direct-to-cloud params: key, bucket, acl, Content-Type, Content-Disposition, x-amz-meta-*, cache-control
- resumable APIs: create/init → upload/chunk → complete/finalize
- background processors: thumbnails, PDF→image, virus scan queues

Đây là các điểm có thể thay đổi validation hoặc metadata ở từng bước.