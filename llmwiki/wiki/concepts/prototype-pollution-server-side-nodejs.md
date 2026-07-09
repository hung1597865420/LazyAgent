---
title: Server-Side Prototype Pollution (Node.js)
type: concept
related: [[Prototype Pollution]]
---

Trên Node.js, prototype pollution có thể dẫn đến RCE nếu polluted properties đi vào child_process, template engines, hoặc require paths.

Các sink phổ biến:
- merge utilities
- Express/query parsers
- YAML load không an toàn
- JSON.parse rồi merge vào object có prototype

Impact phụ thuộc version package và gadget availability.