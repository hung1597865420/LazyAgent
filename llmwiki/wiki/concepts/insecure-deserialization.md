---
title: Insecure Deserialization
type: concept
related: [[Insecure Deserialization Attack Surface]]
---

Insecure deserialization là lỗi khi dữ liệu do attacker kiểm soát được đưa vào các hàm unmarshal/native deserializer của ngôn ngữ.

Hệ quả có thể gồm:
- remote code execution
- authentication bypass
- logic manipulation

Nguyên tắc:
- mọi serialized object, session blob, hoặc opaque binary token đều phải được xem là không tin cậy
- chỉ nên dùng pattern an toàn như schema validation, `yaml.safe_load`, hoặc không dùng custom serialization