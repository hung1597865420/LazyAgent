---
title: Information Disclosure Triage Rubric
type: entity
related: [[Information Disclosure]]
---

Các mức triage được nhắc đến:

- Critical: credentials/keys, signed URL secrets, config dumps, unrestricted admin/observability panels
- High: reachable CVEs, cross-tenant data, caches serving cross-user content
- Medium: internal paths/hosts enabling LFI/SSRF pivots, source maps revealing hidden endpoints
- Low: generic headers, marketing versions, intended documentation without exploit path

Đây là rubric để phân loại mức độ nghiêm trọng của disclosure.