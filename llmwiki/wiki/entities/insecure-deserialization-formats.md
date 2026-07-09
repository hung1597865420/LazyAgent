---
title: Insecure Deserialization Formats
type: entity
related: [[Insecure Deserialization]]
---

Các format/serializer được nhắc đến:

- Java native serialization
- XStream
- Jackson
- Fastjson
- YAML / SnakeYAML
- Python `pickle`
- Python `marshal`
- Python `shelve`
- PHP `unserialize()`
- Phar deserialization
- .NET `BinaryFormatter`
- Json.NET TypeNameHandling
- ViewState
- Ruby `Marshal.load`
- YAML.load
- Node.js `node-serialize`
- `unserialize.js`

Đây là các format cần kiểm tra khi nhận input không tin cậy.