---
title: JWT Misuse
type: concept
related: [[Dependency Injection Gaps]]
---

JWT trong FastAPI có thể bị dùng sai ở nhiều điểm:

- Decode mà không verify chữ ký
- Chấp nhận token unsigned hoặc attacker-signed
- Nhầm lẫn thuật toán HS256/RS256 nếu không pin chặt
- Cho phép `kid` header injection để điều hướng key lookup
- Thiếu kiểm tra issuer/audience, dẫn đến reuse token giữa các service

Kiểm tra:
- Thử token giả, token không chữ ký, và token với header bất thường
- Xác minh thuật toán và key lookup được cố định
- Kiểm tra ràng buộc issuer/audience

Mục tiêu là đảm bảo token không thể bị giả mạo hoặc tái sử dụng ngoài phạm vi dự kiến.