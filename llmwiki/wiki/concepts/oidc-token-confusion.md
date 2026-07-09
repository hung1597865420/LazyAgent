---
title: OIDC Token Confusion
type: concept
related: [[JWT Claims Validation]]
---

OIDC token confusion xảy ra khi hệ thống chấp nhận sai loại token hoặc token dành cho client/service khác.

Các dạng chính:
- Access token dùng như ID token hoặc ngược lại
- OIDC mix-up giữa client A và client B
- PKCE downgrade: thiếu yêu cầu S256, chấp nhận plain hoặc thiếu `code_verifier`
- State/nonce yếu hoặc thiếu dẫn đến CSRF hoặc login interception
- Device/backchannel flow bị dùng bởi client không mong muốn

Nguyên tắc:
- Phân biệt rõ token type, client, và redirect flow