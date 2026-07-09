---
title: Python Pickle Deserialization
type: concept
related: [[Insecure Deserialization]]
---

Python `pickle` có thể thực thi code trong quá trình unpickling.

Điểm chính:
- `pickle.loads` trên input do user kiểm soát là nguy hiểm
- `yaml.load` không an toàn nếu không dùng `yaml.safe_load`
- payload thường được encode qua base64 để truyền qua cookie hoặc parameter