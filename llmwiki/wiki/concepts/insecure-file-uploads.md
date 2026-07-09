---
title: Insecure File Uploads
type: concept
related: [[Insecure File Uploads Attack Surface]]
---

Insecure file uploads là nhóm lỗi khi file do người dùng tải lên có thể dẫn đến:
- remote code execution
- stored XSS
- malware distribution
- storage takeover
- DoS

Nguyên tắc cốt lõi:
- upload security là thuộc tính của cả pipeline, không chỉ một endpoint
- authorization và validation phải đúng ở mọi bước: client → ingress → storage → processors → serving
- không được execute hoặc inline-render nội dung không tin cậy