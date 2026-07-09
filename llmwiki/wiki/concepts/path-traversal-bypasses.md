---
title: Path Traversal Bypasses
type: concept
related: [[Path Traversal / LFI / RFI]]
---

Các bypass path traversal thường dựa trên:

- single/double URL encoding
- mixed case
- overlong UTF-8
- UTF-16
- path normalization oddities
- mixed separators
- dot tricks
- absolute path injection
- alias/root mismatch
- upstream vs backend decoding

Mục tiêu là vượt qua join path hoặc canonicalization yếu.