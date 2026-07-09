---
title: XXE Impact
type: concept
related: [[XXE]]
---

Tác động của XXE:
- disclosure of credentials, keys, configs, code, environment secrets
- access to cloud metadata/token services
- access to internal admin panels
- denial of service
- code execution trong stack không an toàn

Impact phụ thuộc vào parser, transformer, và network/file access.