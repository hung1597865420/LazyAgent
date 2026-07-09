---
title: Firebase Security Testing Methodology
type: concept
related: [[Firebase / Firestore Attack Surface]]
---

Quy trình kiểm thử bảo mật cho Firebase/Firestore:

1. Extract config: lấy project config từ client bundle
2. Obtain principals: thu thập token cho unauth, anonymous, user A/B, admin
3. Build matrix: resource × action × principal trên Firestore/Realtime/Storage/Functions
4. SDK vs REST: thực thi mọi action qua cả hai đường
5. Seed IDs: bắt đầu từ list/query để thu document IDs
6. Cross-principal: hoán đổi document paths, tenants, user IDs giữa các principal

Mục tiêu là phát hiện lệch chuẩn giữa rules, auth, storage, và function execution.