---
title: Business Logic Flaws
type: concept
related: [[Business Logic Flaws]]
---

Business logic flaws là các lỗi khai thác chức năng dự định của hệ thống để vi phạm domain invariants: chuyển tiền mà không trả tiền, vượt giới hạn, giữ lại đặc quyền, hoặc bỏ qua review.

Đặc điểm:
- Cần mô hình hóa nghiệp vụ, không chỉ payload
- Thường xuất hiện khi client hoặc bước trước đó được tin quá mức
- Tác động lên trạng thái bền vững của hệ thống

Nguyên tắc:
- Bảo vệ invariants ở service thực thi state change
- Không tin tính toán hay sequencing từ client