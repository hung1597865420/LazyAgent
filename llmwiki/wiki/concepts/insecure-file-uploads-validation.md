---
title: Insecure File Uploads Validation
type: concept
related: [[Insecure File Uploads Testing Methodology]]
---

Validation cần chứng minh:

- execution hoặc rendering của active content
- filter bypass với bằng chứng khi tải xuống
- header weaknesses như thiếu `nosniff` hoặc thiếu `attachment`
- race/pipeline gap như truy cập trước AV/CDR hoặc extraction ngoài thư mục dự kiến
- reproducible steps với request/response đầy đủ