---
title: Velocity / Freemarker / Thymeleaf SSTI
type: concept
related: [[Server-Side Template Injection]]
---

Nhóm Java template engines này thường dẫn tới SpEL, reflection, hoặc gadget như Freemarker Execute.

Tài liệu nhấn mạnh rằng `Runtime.exec()` không tự động trả stdout; cần đọc InputStream nếu muốn output phản chiếu.

Thymeleaf chỉ exploitable khi attacker kiểm soát template source, không phải chỉ model variable.