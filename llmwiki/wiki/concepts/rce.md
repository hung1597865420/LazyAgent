---
title: RCE
type: concept
related: [[RCE Attack Surface]]
---

Remote code execution xảy ra khi input đi tới các primitive thực thi code như command wrappers, dynamic evaluators, template engines, deserializers, media pipelines, hoặc build/runtime tooling.

Mục tiêu kiểm thử:
- tìm sink thực thi
- xác nhận bằng oracle yên tĩnh
- chỉ leo tới shell bền vững khi thật sự cần