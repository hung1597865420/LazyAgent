---
title: Freeze/Seal Gaps
type: entity
related: [[Prototype Pollution Filter Bypasses]]
---

Các gap được nhắc đến:

- pollution trước khi `Object.freeze`
- prototype không bị freeze dù instance đã freeze
- pollution ảnh hưởng object mới tạo sau merge

Điều này khiến hardening cục bộ không đủ nếu prototype vẫn bị ảnh hưởng.