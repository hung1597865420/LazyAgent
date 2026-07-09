---
title: H2.TE Request Smuggling
type: concept
related: [[HTTP Request Smuggling]]
---

H2.TE xảy ra khi attacker inject `transfer-encoding: chunked` trong HTTP/2 headers và front-end chuyển tiếp xuống HTTP/1.1 back-end.

Đặc điểm:
- HTTP/2 spec forbids `transfer-encoding` theo cách này
- Một số front-end vẫn pass through
- Back-end có thể ưu tiên TE hơn CL

Biến thể này phụ thuộc vào hành vi downgrade và normalization của intermediary.