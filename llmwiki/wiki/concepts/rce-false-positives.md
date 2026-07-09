---
title: RCE False Positives
type: concept
related: [[RCE]]
---

Các trường hợp không nên kết luận là RCE:

- chỉ crash hoặc timeout
- command subset bị filter nhưng không có attacker-controlled args
- sandbox/VM hạn chế IO và process spawn
- simulated outputs không xuất phát từ command thực

Cần controlled behavior, không chỉ lỗi hoặc delay.