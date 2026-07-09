---
title: HTTP Request Smuggling
type: concept
related: [[HTTP Request Smuggling Attack Surface]]
---

HTTP request smuggling (HRS) là kỹ thuật khai thác sự bất đồng giữa front-end proxy và back-end server về ranh giới giữa các HTTP request.

Cốt lõi:
- Front-end và back-end parse `Content-Length` và `Transfer-Encoding` khác nhau
- Attacker có thể chèn một request ẩn vào socket của back-end
- Request ẩn này có thể được prepended vào request hợp lệ của người dùng tiếp theo

Tác động:
- bypass front-end security controls
- cross-user session hijacking
- cache poisoning
- response queue poisoning