---
title: Path Traversal Surface Map
type: entity
related: [[Path Traversal / LFI / RFI Testing Methodology]]
---

Các điểm cần map:

- HTTP params như `file`, `path`, `template`, `include`, `page`, `view`, `download`, `export`, `report`, `log`, `dir`, `theme`, `lang`
- upload and conversion pipelines
- archive extract endpoints and background jobs
- server-side template rendering
- reverse proxies và static file servers