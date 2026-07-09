---
title: Path Traversal / LFI / RFI Testing Methodology
type: concept
related: [[Path Traversal / LFI / RFI]]
---

Quy trình kiểm thử:

1. Inventory file operations
2. Identify input joins
3. Probe normalization
4. Compare behaviors
5. Escalate từ disclosure đến execution

Mục tiêu là xác định nơi nào path do user ảnh hưởng được dùng để read/include/write.