---
title: UNION-Based Extraction
type: concept
related: [[SQL Injection]]
---

UNION-based extraction là kỹ thuật dùng `UNION SELECT` để trích xuất dữ liệu khi số cột và kiểu dữ liệu khớp với truy vấn gốc.

Các bước chính:
- xác định column count bằng `ORDER BY n`
- dùng `UNION SELECT null,...`
- align types bằng `CAST`/`CONVERT`
- chuyển output sang text/json nếu cần

Nếu UNION bị filter, chuyển sang error-based hoặc blind.