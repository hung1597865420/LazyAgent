---
title: Firebase Tenant Model
type: entity
related: [[Tenant Isolation]]
---

Mô hình tenant trong Firebase thường có dạng:

- `orgs/<orgId>/...`

Đây là cấu trúc dữ liệu đa tenant cần được bind với membership hoặc custom claim thay vì tin từ client.