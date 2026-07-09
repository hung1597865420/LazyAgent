---
title: Second-Order Deserialization
type: entity
related: [[Advanced Deserialization Techniques]]
---

Second-order deserialization là khi serialized blob được lưu trước và chỉ được trigger sau, ví dụ qua:

- admin export
- cache warm
- batch job

Đây là kiểu trigger trì hoãn, khó phát hiện hơn direct deserialization.