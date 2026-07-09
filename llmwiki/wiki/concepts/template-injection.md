---
title: Template Injection
type: concept
related: [[Django]]
---

Django template engine mặc định auto-escape, nhưng vẫn có thể bị template injection hoặc XSS nếu developer vô tình vô hiệu hóa cơ chế an toàn.

Điểm rủi ro:
- `mark_safe(user_input)`
- Dùng `|safe` với dữ liệu không tin cậy
- `Template(user_input).render(...)` khi người dùng kiểm soát source template
- Jinja2 backend nếu autoescape bị tắt hoặc sandbox cấu hình sai

Tác động:
- XSS
- Trong một số cấu hình Jinja2, có thể dẫn đến SSTI hoặc gadget RCE

Kiểm tra:
- Tìm các chỗ dùng `mark_safe` và `|safe`
- Thử payload như `{{7*7}}` nếu nghi ngờ Jinja2/SSTI
- Xác minh template source có hoàn toàn do server kiểm soát hay không