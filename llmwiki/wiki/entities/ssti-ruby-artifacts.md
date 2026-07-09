---
title: Ruby SSTI Artifacts
type: entity
related: [[ERB / Haml SSTI]]
---

Các artifact Ruby được nhắc đến:

- `` `id` ``
- `IO.popen('id').read`
- `Open3.capture2('id')`
- `system('id')`
- `instance_eval`
- `class_eval`