---
title: Permission Class Gaps
type: concept
related: [[Django]]
---

Trong Django REST Framework, một lỗi phổ biến là các hành động trong cùng một ViewSet không có mức bảo vệ đồng nhất. Ví dụ:

- `list` được bảo vệ nhưng `retrieve` hoặc `update` lại thiếu `permission_classes`
- `@api_view` không khai báo quyền rõ ràng và vô tình kế thừa cấu hình mặc định quá rộng
- Custom permissions chỉ kiểm tra đã đăng nhập nhưng không kiểm tra quyền sở hữu đối tượng
- Admin actions hoặc management commands tự viết nhưng không kiểm tra staff/superuser

Hệ quả thường gặp là IDOR, leo thang đặc quyền, hoặc truy cập trái phép vào dữ liệu nhạy cảm.

Cách kiểm tra:
- Lập ma trận auth theo từng endpoint và từng HTTP method
- So sánh quyền giữa các action chuẩn và custom action
- Kiểm tra object-level permission có lọc theo `request.user` hay không

Nguyên tắc phòng tránh:
- Khai báo quyền rõ ràng cho từng route/action
- Áp dụng object-level authorization trên queryset và `get_object()`
- Không dựa vào chỉ xác thực đăng nhập để bảo vệ dữ liệu nhạy cảm