---
title: XSS via Response Headers
type: concept
related: [[HTTP Header Injection]]
---

Một số response header có thể dẫn đến XSS hoặc script-like navigation nếu được phản chiếu không an toàn.

Ví dụ:
- `Location: javascript:...`
- `Location: data:text/html,...`
- `Refresh: 0; url=javascript:...`
- `Referer` hoặc `User-Agent` bị echo vào page/debug header

Nguyên tắc:
- Không phản chiếu header không tin cậy vào sink hiển thị hoặc redirect