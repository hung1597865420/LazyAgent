---
title: CDN and Cache Keys
type: concept
related: [[Information Disclosure]]
---

Lỗi cache key xảy ra khi CDN/proxy không đưa các yếu tố identity vào cache key.

Các vấn đề chính:
- thiếu `Authorization` hoặc tenant headers trong key
- `Vary` cấu hình sai
- `206 partial content` kết hợp stale cache làm lộ fragment

Đây là nguồn cross-user content leakage phổ biến.