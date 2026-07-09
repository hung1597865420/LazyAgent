---
title: Header Injection Attack Surface
type: concept
related: [[HTTP Header Injection]]
---

Bề mặt tấn công của header injection gồm:

- Input từ query/body/path được echo vào `Set-Cookie`, `Location`, `Content-Type`, `Content-Disposition`, `Link`, custom `X-*`
- Request headers được phản chiếu vào response như `Referer`, `User-Agent`, `X-Forwarded-*`
- Webhook/callback flows xây outbound request từ URL do user cung cấp
- Outbound email headers như `To`, `From`, `Subject` lấy từ input người dùng