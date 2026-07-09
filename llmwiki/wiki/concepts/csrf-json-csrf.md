---
title: CSRF JSON CSRF
type: concept
related: [[CSRF Method and Content-Type Abuse]]
---

JSON CSRF xảy ra khi server chấp nhận JSON từ `text/plain` hoặc form-encoded bodies.

Dấu hiệu:
- Framework parse JSON từ `text/plain`
- Form fields như `data[foo]=bar` được chuyển thành cấu trúc JSON
- Duplicate keys được xử lý lỏng lẻo

Nguyên tắc:
- Chỉ chấp nhận JSON từ content-type hợp lệ và parser an toàn