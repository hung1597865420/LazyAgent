---
title: Client-Side Redirect Vectors
type: concept
related: [[Open Redirect]]
---

Các vector redirect phía client gồm:

- `window.location`
- `location.assign`
- `location.href`
- `location.replace`
- meta refresh
- SPA router navigation

Nếu các API này nhận input từ người dùng mà không kiểm soát đích cuối, có thể dẫn đến open redirect.