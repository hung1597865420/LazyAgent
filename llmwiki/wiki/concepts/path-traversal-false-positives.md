---
title: Path Traversal / LFI / RFI False Positives
type: concept
related: [[Path Traversal / LFI / RFI]]
---

Các trường hợp không nên kết luận là lỗ hổng:

- virtual paths không map tới filesystem
- path đã canonicalize và bị constrain bởi allowlist/root
- wrappers bị disable và template là constant
- archive extractor sanitize path và enforce destination directory

Cần phân biệt giữa đường dẫn logic và truy cập filesystem thực.