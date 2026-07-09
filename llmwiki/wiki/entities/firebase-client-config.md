---
title: Firebase Client Config
type: entity
related: [[Firebase Security Testing Methodology]]
---

Cấu hình client Firebase thường được trích xuất từ bundle:

- `apiKey`
- `authDomain`
- `projectId`
- `appId`
- `storageBucket`
- `messagingSenderId`

`firebase.apps[0].options` là nguồn thường dùng để lấy các giá trị này.