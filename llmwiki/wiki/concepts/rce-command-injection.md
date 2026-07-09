---
title: Command Injection
type: concept
related: [[RCE]]
---

Command injection là khi input điều khiển lệnh OS thông qua shell wrappers, CLI, hoặc system utilities.

Các hướng khai thác thường gặp:
- delimiters/operators
- argument injection
- path and builtin confusion
- evasion qua whitespace, token splitting, base64 stagers

Đây là một trong các đường dẫn phổ biến nhất tới RCE.