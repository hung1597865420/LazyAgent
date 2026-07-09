---
title: CORS Misconfiguration
type: concept
related: [[FastAPI Attack Surface]]
---

CORS trong FastAPI/Starlette có thể bị cấu hình quá rộng.

Rủi ro chính:
- `allow_origin_regex` quá rộng
- Reflect origin mà không validate
- Cho phép credentialed requests với origin permissive
- Preflight và actual request có hành vi khác nhau

Kiểm tra:
- So sánh response preflight và request thật
- Thử origin lạ, regex rộng, và credentialed request

Khuyến nghị:
- Whitelist origin chặt chẽ
- Không phản chiếu origin nếu chưa xác thực
- Kiểm tra kỹ cấu hình credentials