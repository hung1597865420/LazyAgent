---
title: Open Redirect False Positives
type: concept
related: [[Open Redirect]]
---

Các trường hợp không nên kết luận là open redirect:

- redirect chỉ tới relative same-origin paths với normalization tốt
- OAuth redirect_uri đã pre-register và verifier chặt
- validator dùng một canonical parser duy nhất
- có prompt hiển thị đích cuối trước khi điều hướng

Cần phân biệt giữa redirect hợp lệ và redirect bị kiểm soát bởi attacker.