---
title: Mass Assignment Shape Variants
type: concept
related: [[Mass Assignment]]
---

Các biến thể shape của input có thể làm lệch binder hoặc validator:

- arrays vs scalars
- nested JSON
- objects dưới key bất ngờ
- dot/bracket paths
- duplicate keys và precedence
- sparse/patch formats như JSON Patch và JSON Merge Patch

Đây là nhóm kỹ thuật để reach nested fields hoặc bypass parser assumptions.