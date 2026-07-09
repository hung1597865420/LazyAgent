---
title: .NET Serialization Primitives
type: entity
related: [[Deserialization and Expression Language RCE]]
---

Các primitive .NET được nhắc đến:

- BinaryFormatter
- DataContractSerializer
- ViewState không có MAC

Chúng có thể dẫn tới deserialization RCE nếu nhận input không tin cậy.