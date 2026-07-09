---
title: Cache Poisoning via Header Injection
type: concept
related: [[HTTP Header Injection]]
---

Cache poisoning xảy ra khi input ảnh hưởng đến response body hoặc link nhưng không được đưa vào cache key.

Các dạng chính:
- unkeyed input → keyed response
- `Vary` manipulation
- `X-Forwarded-Proto` / `X-Forwarded-Host` poisoning
- `Cache-Control` injection
- web cache deception

Mục tiêu là làm cache lưu và phát tán response do attacker kiểm soát.