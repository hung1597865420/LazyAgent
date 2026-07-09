---
title: Template Injection (Jinja2)
type: concept
related: [[FastAPI Attack Surface]]
---

Khi FastAPI dùng Jinja2 templates, template injection có thể xảy ra nếu dữ liệu không tin cậy được đưa vào source template hoặc filter/global nguy hiểm.

Ví dụ kiểm tra:
```jinja2
{{7*7}}
{{cycler.__init__.__globals__['os'].popen('id').read()}}
```

Điểm cần xem:
- Autoescape có bật hay không
- Custom filters/globals có an toàn không

Mục tiêu là xác định khả năng SSTI hoặc RCE qua template rendering.