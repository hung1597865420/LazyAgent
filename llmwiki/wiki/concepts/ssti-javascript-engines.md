---
title: Handlebars / Nunjucks / EJS SSTI
type: concept
related: [[Server-Side Template Injection]]
---

Nhóm JavaScript template engines có thể dẫn tới RCE qua `require`, constructor walk, hoặc custom helpers.

EJS là inline JavaScript trực tiếp; Nunjucks thường cần constructor walk; Handlebars nguy hiểm hơn khi custom helpers hoặc prototype pollution mở lại surface.