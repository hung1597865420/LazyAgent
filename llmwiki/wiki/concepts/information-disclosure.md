---
title: Information Disclosure
type: concept
related: [[Information Disclosure Attack Surface]]
---

Information disclosure là nhóm vấn đề làm lộ code, cấu hình, định danh, trust boundary, hoặc dữ liệu nhạy cảm qua response, artifact, header, schema, hay endpoint debug.

Nguyên tắc:
- Mọi byte phản hồi, artifact, và header đều có thể là intelligence
- Cần minimize, normalize, và scope disclosure trên mọi kênh
- Disclosure thường là chất xúc tác để khai thác tiếp RCE, LFI, SSRF, hoặc auth bypass