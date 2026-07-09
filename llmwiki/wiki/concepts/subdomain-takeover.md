---
title: Subdomain Takeover
type: concept
related: [[Subdomain Takeover Attack Surface]]
---

Subdomain takeover là tình huống attacker chiếm quyền phục vụ nội dung trên một subdomain đáng tin cậy bằng cách claim resource được trỏ tới bởi dangling DNS hoặc cấu hình provider bị ràng buộc sai.

Hậu quả chính:
- phishing trên trusted origin
- cookie và CORS pivot
- OAuth redirect abuse
- CDN cache poisoning