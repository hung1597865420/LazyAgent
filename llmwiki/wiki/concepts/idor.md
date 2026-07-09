---
title: IDOR
type: concept
related: [[IDOR Attack Surface]]
---

IDOR/BOLA là lỗi xác thực ở mức object-level authorization, dẫn đến truy cập dữ liệu cross-account và thay đổi trạng thái trái phép.

Nguyên tắc cốt lõi:
- Mọi object reference phải được xem là không tin cậy
- Authorization phải bind subject, action, và object cụ thể trên mỗi request
- Không được giả định identifier opaque là an toàn