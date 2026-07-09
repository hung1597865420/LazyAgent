---
title: Firebase Firestore and Storage Endpoints
type: entity
related: [[Firebase / Firestore Attack Surface]]
---

Các endpoint REST quan trọng trong Firebase/Firestore:

- Firestore REST: `https://firestore.googleapis.com/v1/projects/<project>/databases/(default)/documents/<path>`
- Realtime Database: `https://<project>.firebaseio.com/.json`
- Storage REST: `https://storage.googleapis.com/storage/v1/b/<bucket>`

Đây là các contract truy cập dữ liệu cần được kiểm tra về auth và rules.