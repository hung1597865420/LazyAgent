---
title: Deserialization and Expression Language RCE
type: concept
related: [[RCE]]
---

Insecure deserialization và expression language injection có thể dẫn tới gadget chains hoặc gọi trực tiếp Runtime/ProcessBuilder/exec.

Các ngôn ngữ/stack được nhắc đến:
- Java
- .NET
- PHP
- Python/Ruby
- OGNL/SpEL/MVEL/EL

Đây là nhóm sink quan trọng cần kiểm tra khi input đi vào parser hoặc evaluator.