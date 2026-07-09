---
title: CSRF Login and Logout CSRF
type: concept
related: [[CSRF]]
---

Login/logout CSRF có thể ép người dùng đăng xuất hoặc đăng nhập bằng credentials của attacker.

Kịch bản:
- Force logout để xóa CSRF token
- Chaining login CSRF để bind victim vào account của attacker

Nguyên tắc:
- Login/logout cũng phải có bảo vệ chống CSRF