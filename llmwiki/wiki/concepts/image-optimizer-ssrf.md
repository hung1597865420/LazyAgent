---
title: Image Optimizer SSRF
type: concept
related: [[Next.js Attack Surface]]
---

`next/image` có thể trở thành nguồn SSRF nếu cấu hình remote loader hoặc domain pattern quá rộng.

Rủi ro:
- `images.domains` hoặc `remotePatterns` quá broad
- Custom loaders theo redirect chain
- DNS rebinding, internal host access, IPv4/IPv6 variants
- Cache poisoning do khác biệt normalization URL

Kiểm tra:
- Thử internal hosts và biến thể địa chỉ
- Quan sát redirect behavior
- Kiểm tra cache key và normalization

Khuyến nghị:
- Whitelist nguồn ảnh chặt chẽ
- Không cho phép loader tùy ý fetch URL ngoài kiểm soát