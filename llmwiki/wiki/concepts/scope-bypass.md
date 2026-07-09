---
title: Scope Bypass
type: concept
related: [[Dependency Injection Gaps]]
---

Scope enforcement trong FastAPI có thể bị bypass nếu chỉ kiểm tra token hợp lệ mà không kiểm tra scope đúng cách.

Rủi ro:
- Chấp nhận bất kỳ token hợp lệ nào, không xét scope tối thiểu
- Không nhất quán giữa router-level và route-level scope enforcement

Kiểm tra:
- So sánh các route yêu cầu scope khác nhau
- Xác minh token có scope tối thiểu nhưng không đủ quyền có bị chặn hay không

Nguyên tắc:
- Scope phải được kiểm tra theo từng operation
- Không suy diễn quyền từ việc token còn hiệu lực