---
title: File Handling Risks
type: concept
related: [[Django]]
---

Xử lý file trong Django có thể dẫn đến lộ dữ liệu, XSS hoặc path traversal nếu cấu hình và validation không chặt.

Các rủi ro chính:
- `MEDIA_ROOT` được phục vụ trực tiếp trong DEBUG hoặc qua nginx cấu hình sai
- Custom download view dùng path do người dùng cung cấp
- Upload SVG/HTML với `Content-Type` cho phép thực thi script
- Thiếu kiểm tra kích thước và loại file

Kiểm tra:
- Xem cách file được lưu và phục vụ
- Thử đường dẫn traversal trong các endpoint tải file
- Kiểm tra MIME type và chính sách upload

Khuyến nghị:
- Không phục vụ media nhạy cảm trực tiếp nếu không cần
- Validate file type/size chặt chẽ
- Không tin vào path do client cung cấp