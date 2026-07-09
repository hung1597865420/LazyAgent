---
title: Prototype Pollution
type: concept
related: [[Prototype Pollution Attack Surface]]
---

Prototype pollution là lỗi làm nhiễm bẩn shared object prototypes như `Object.prototype` hoặc `Array.prototype`.

Hệ quả chính:
- application logic bypass
- denial of service
- remote code execution trên Node.js qua gadget chains

Nguyên tắc phòng tránh:
- không merge user input một cách không an toàn
- lọc key đặc biệt
- dùng null-prototype objects