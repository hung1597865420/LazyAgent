---
title: Insecure Deserialization Detection Signals
type: entity
related: [[Insecure Deserialization Reconnaissance]]
---

Các tín hiệu phát hiện được nhắc đến:

- base64 blobs có magic bytes
- Java magic bytes `ac ed 00 05`
- PHP prefixes `O:`, `a:`, `s:`
- .NET BinaryFormatter prefix `00 01 00 00 00 ff ff ff ff`
- `Content-Type` binary hoặc custom serialization
- framework indicators như Spring, Struts, JSF, Symfony sessions

Chúng giúp nhận diện format và stack.