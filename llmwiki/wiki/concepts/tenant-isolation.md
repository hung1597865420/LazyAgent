---
title: Tenant Isolation
type: concept
related: [[Firestore Rules Security]]
---

Ứng dụng Firebase thường dùng mô hình đa tenant như `orgs/<orgId>/...`.

Nguyên tắc:
- Tenant phải được bind từ server context, membership doc, hoặc custom claim
- Không tin tenant từ client payload, header, subdomain, hoặc query nếu chưa đối chiếu với identity

Kiểm tra:
- Giữ token cố định nhưng đổi org header/subdomain/query
- Đảm bảo export/report functions chạy theo scope của caller

Mục tiêu là ngăn cross-tenant access và data leakage.