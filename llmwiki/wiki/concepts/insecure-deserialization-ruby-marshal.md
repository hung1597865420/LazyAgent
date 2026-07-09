---
title: Ruby Marshal Deserialization
type: concept
related: [[Insecure Deserialization]]
---

Ruby `Marshal.load` trên dữ liệu do user kiểm soát có thể dẫn đến gadget chains tùy theo version và context của Rails/Devise.

Nguyên tắc:
- không deserialize object không tin cậy bằng Marshal
- ưu tiên format an toàn hơn và schema validation