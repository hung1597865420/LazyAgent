---
title: Dynamic Template Resolution
type: concept
related: [[Local File Inclusion (LFI)]]
---

Khi template name được lấy từ input người dùng, engine có thể include file ngoài ý muốn.

Các engine được nhắc đến:
- PHP include/require
- Smarty/Twig/Blade
- JSP/FreeMarker/Velocity
- ejs/handlebars/pug

Rủi ro tăng cao khi theme/lang/template được resolve động từ user input.