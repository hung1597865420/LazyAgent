---
title: Insecure File Uploads Bypass Techniques
type: concept
related: [[Insecure File Uploads]]
---

Các nhóm bypass chính:

- validation gaps: client-side only, trust multipart headers, extension allowlists không có content inspection
- evasion tricks: double extensions, mixed case, hidden dotfiles, extra dots, long paths
- multipart name/filename/path discrepancies
- duplicate parameters và late precedence

Đây là các kỹ thuật để vượt qua kiểm tra upload naive.