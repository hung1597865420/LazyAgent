---
title: Trusted Types Bypass
type: concept
related: [[XSS]]
---

Trusted Types bypass thường đến từ custom policies trả về string chưa sanitize hoặc từ sinks không được Trusted Types bao phủ.

Các pivot phổ biến:
- policy whitelist sai
- CSS sinks
- URL handlers
- gadget chain sang sink khác

Trusted Types chỉ hiệu quả nếu policy và coverage đều chặt.