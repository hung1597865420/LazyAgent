---
title: Insecure Deserialization Bypass Methods
type: concept
related: [[Insecure Deserialization]]
---

Các cách bypass phổ biến:

- encoding layers như base64/gzip/serialize
- alternative parameters lưu cùng session
- đổi content-type hoặc vị trí parameter
- type confusion giữa array và object
- Unicode/UTF-7 smuggling trong legacy PHP contexts

Mục tiêu là làm lệch branch của deserializer hoặc bypass filter.