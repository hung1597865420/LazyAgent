---
title: Header and Method Control
type: concept
related: [[SSRF]]
---

Một số SSRF sink chỉ trở nên nguy hiểm khi attacker điều khiển được headers hoặc HTTP method.

Điều này đặc biệt quan trọng với metadata endpoints như IMDSv2, GCP, và 9Router.

Nếu sink không set được header/method, cần tìm intermediary có khả năng đó.