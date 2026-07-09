---
title: SSTI Validation Artifacts
type: entity
related: [[SSTI Validation]]
---

Các artifact cần có khi validate:

- two distinct expressions evaluating correctly
- object access / runtime reflection
- DNS lookup
- sleep with measurable delta
- file written to known path
- command output in response
- minimal payload