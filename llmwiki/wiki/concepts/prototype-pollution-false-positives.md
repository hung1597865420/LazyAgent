---
title: Prototype Pollution False Positives
type: concept
related: [[Prototype Pollution]]
---

Các trường hợp dễ nhầm:

- parser strip `__proto__` trước merge
- framework dùng `Object.create(null)`
- key chỉ echo trong JSON nhưng không merge vào object graph
- client-side pollution bị chặn bởi frozen prototypes
- WAF chặn payload và encoding thay thế cũng bị chặn

Cần behavioral proof, không chỉ reflected key.