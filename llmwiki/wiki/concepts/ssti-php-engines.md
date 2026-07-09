---
title: Smarty / Twig / Blade SSTI
type: concept
related: [[Server-Side Template Injection]]
---

Nhóm PHP template engines có các surface khác nhau theo version và cấu hình sandbox.

- Twig có gadget lịch sử và các bypass phụ thuộc version/extensions
- Smarty có surface lịch sử qua `{php}` và static-method/reflection paths
- Blade nguy hiểm khi user input đi vào `render`, `compileString`, hoặc `@php` block