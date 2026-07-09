---
title: CSRF Token and Origin Validation
type: concept
related: [[CSRF]]
---

Anti-CSRF token phải được kiểm tra chặt chẽ và gắn với ngữ cảnh phù hợp.

Kiểm tra cần có:
- Token trong hidden input, meta tag, hoặc custom header
- Không cho phép remove/reuse token giữa request hoặc giữa session
- Token phải bind với method/path nếu thiết kế yêu cầu
- Server phải kiểm tra `Origin` và/hoặc `Referer` trên state-changing requests
- Không chấp nhận null/missing/cross-origin values nếu không có lý do rõ ràng