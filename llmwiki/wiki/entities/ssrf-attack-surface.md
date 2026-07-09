---
title: SSRF Attack Surface
type: entity
related: [[SSRF]]
---

Các bề mặt attack surface được nhắc đến:

- outbound HTTP/HTTPS fetchers
- non-HTTP protocols via URL handlers
- service-to-service hops through gateways and sidecars
- cloud and platform metadata endpoints
- indirect sources như previews, analytics, import/export jobs, webhooks
- protocol-translating services
- GraphQL resolvers
- background crawlers
- repository/package managers
- calendar fetchers