---
title: Refresh Token and Session Security
type: concept
related: [[JWT Claims Validation]]
---

Refresh token và session cần được quản lý như một bề mặt tấn công riêng.

Rủi ro:
- Không enforce rotation, cho phép reuse refresh token cũ vô thời hạn
- Không có reuse detection
- JWT sống quá lâu và không revoke được sau logout
- Session fixation qua session identifier hoặc cookie do attacker kiểm soát

Nguyên tắc:
- Rotation và revocation phải là bắt buộc
- Session phải được bind với context hợp lệ