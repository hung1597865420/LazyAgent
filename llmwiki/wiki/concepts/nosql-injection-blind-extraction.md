---
title: Blind Data Extraction via $regex
type: concept
related: [[NoSQL Injection]]
---

Khi kết quả truy vấn không được phản ánh trực tiếp, có thể dùng `$regex` để suy ra giá trị từng ký tự.

Kỹ thuật:
- thử prefix `^a`, `^b`, ...
- dùng boolean oracle, redirect, hoặc timing
- binary search để giảm số request

Áp dụng cho password, token, reset code, API key.