---
title: Parser and Validator Gaps
type: entity
related: [[Mass Assignment Advanced Techniques]]
---

Các gap parser/validator được nhắc đến:

- validators chạy post-bind
- extra fields không được cover
- unknown fields bị drop ở response nhưng vẫn persist
- allowlists không nhất quán giữa mobile/web/gateway
- alt encodings bypass validation pipeline

Đây là nguyên nhân khiến field không mong muốn vẫn được lưu.