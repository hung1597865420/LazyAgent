---
title: File Upload Risks
type: concept
related: [[FastAPI Attack Surface]]
---

Upload file trong FastAPI có thể dẫn đến traversal hoặc lưu file sai vị trí nếu không kiểm soát tên và đường dẫn.

Rủi ro:
- `UploadFile.filename` chứa control characters hoặc path traversal
- Không enforce storage root
- Symlink following ngoài ý muốn
- Encoding tên file, dot segments, NUL-like bytes gây khác biệt xử lý

Kiểm tra:
- Thử tên file bất thường và đường dẫn traversal
- Xác minh storage path và URL phục vụ file

Khuyến nghị:
- Chuẩn hóa tên file
- Giới hạn root lưu trữ
- Không tin vào filename do client cung cấp