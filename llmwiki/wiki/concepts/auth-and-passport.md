---
title: Auth and Passport
type: concept
related: [[NestJS Attack Surface]]
---

Cơ chế auth của NestJS thường dựa trên `@nestjs/passport`, JWT strategy, và đôi khi kết hợp session.

Rủi ro chính:
- `ignoreExpiration` bật sai
- `algorithms` không được pin chặt, dẫn đến `none` hoặc HS/RS confusion
- `secretOrKey` yếu
- Không enforce audience/issuer, cho phép reuse token giữa service
- `validate()` trả về full DB record làm lộ sensitive fields qua `req.user`
- Nhiều strategy cùng tồn tại nhưng một strategy có thể bypass strategy khác
- Custom guard trả `true` cho unauthenticated như một dạng optional auth
- So sánh chuỗi thường thay vì bcrypt/argon2 trong local strategy

Khuyến nghị:
- Pin thuật toán và kiểm tra issuer/audience
- Chỉ trả về dữ liệu tối thiểu từ `validate()`
- Không coi token hợp lệ là đủ nếu chưa kiểm tra ngữ cảnh và quyền