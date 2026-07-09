---
title: HTTP Request Smuggling Attack Surface
type: concept
related: [[HTTP Request Smuggling]]
---

Bề mặt tấn công của request smuggling gồm:

- CDN / load balancer trước origin server
- Reverse proxy chains
- API gateways forwarding đến microservices
- HTTP/2 front-end sang HTTP/1.1 back-end translation
- Tunneling servers hoặc WAFs terminate rồi forward lại request

Các topology này tạo ra cơ hội cho parser disagreement giữa các hop.