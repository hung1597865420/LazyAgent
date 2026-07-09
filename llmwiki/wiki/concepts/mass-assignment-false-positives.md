---
title: Mass Assignment False Positives
type: concept
related: [[Mass Assignment]]
---

Các trường hợp không nên kết luận là mass assignment:

- server recomputes derived fields và bỏ qua input client
- field read-only được enforce nhất quán trên mọi encoding
- chỉ thay đổi UI, không có persisted effect

Cần phân biệt giữa hiển thị và trạng thái lưu trữ thực sự.