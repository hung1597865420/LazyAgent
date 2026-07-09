---
title: Path Traversal / LFI / RFI Validation
type: concept
related: [[Path Traversal / LFI / RFI Testing Methodology]]
---

Validation cần chứng minh:

- traversal read ra ngoài root
- LFI include file local hoặc wrapper output an toàn
- RFI chứng minh remote fetch bằng OAST hoặc output điều khiển được
- Zip Slip ghi file ra ngoài target
- có before/after paths, requests, hashes/lengths để tái lập