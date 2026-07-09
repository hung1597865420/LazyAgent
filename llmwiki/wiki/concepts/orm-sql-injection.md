---
title: ORM SQL Injection
type: concept
related: [[Django]]
---

Dù Django ORM an toàn hơn SQL thủ công, vẫn có thể phát sinh SQL injection khi code dùng các API nguy hiểm hoặc ghép chuỗi trực tiếp.

Mẫu dễ lỗi:
- `raw()` với f-string hoặc nối chuỗi
- `extra(where=[...])`
- `RawSQL` không tham số hóa đúng cách
- Các truy vấn filter/search tự xây dựng bằng chuỗi

Ví dụ nguy hiểm:
```python
User.objects.raw(f"SELECT * FROM auth_user WHERE username = '{user_input}'")
User.objects.extra(where=[f"username = '{user_input}'"])
```

Kiểm tra bằng payload như `' OR 1=1 --` hoặc payload thời gian để xác nhận injection.

Khuyến nghị:
- Dùng tham số hóa thay vì nối chuỗi
- Tránh `extra()` và `raw()` nếu không thật sự cần
- Rà soát các điểm dùng `RawSQL` và annotation phức tạp