---
title: .NET Deserialization
type: concept
related: [[Insecure Deserialization]]
---

.NET deserialization với `BinaryFormatter`, `LosFormatter`, hoặc Json.NET type handling có thể dẫn đến RCE hoặc view state forgery.

Điểm chính:
- `BinaryFormatter` không an toàn trên input không tin cậy
- `TypeNameHandling` của Json.NET có thể cho phép attacker chọn type
- ViewState phụ thuộc MAC và machine keys

Các cơ chế này cần được vô hiệu hóa hoặc khóa chặt trên dữ liệu untrusted.