---
title: Java Deserialization
type: concept
related: [[Insecure Deserialization]]
---

Java deserialization là bề mặt rủi ro khi `ObjectInputStream` hoặc các mapper tương đương nhận dữ liệu không tin cậy.

Điểm chính:
- gadget chains phụ thuộc classpath
- có thể dẫn đến callback hoặc command execution
- Jackson/JSON typing cũng có thể tạo type confusion nếu cho phép attacker chọn type

Cần fingerprint version và thư viện trước khi chọn chain.