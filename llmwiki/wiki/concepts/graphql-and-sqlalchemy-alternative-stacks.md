---
title: GraphQL and SQLAlchemy Alternative Stacks
type: concept
related: [[FastAPI Attack Surface]]
---

Nếu ứng dụng FastAPI tích hợp stack khác, cần kiểm tra thêm các bề mặt đặc thù.

GraphQL:
- Resolver-level authorization
- IDOR trên node/global IDs

SQLModel/SQLAlchemy:
- Raw query usage
- Row-level authorization gaps

Đây là các lớp bổ sung có thể tạo ra lỗ hổng ngoài router/dependency thông thường.