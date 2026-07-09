---
title: NS Delegation Takeover
type: concept
related: [[Subdomain Takeover]]
---

Nếu child zone được delegate tới nameserver dưới một domain đã hết hạn, attacker có thể đăng ký lại domain đó và host authoritative NS.

Khi kiểm soát NS được delegate, attacker có thể publish records cho toàn bộ subzone.

Đây là takeover có phạm vi rộng hơn CNAME takeover.