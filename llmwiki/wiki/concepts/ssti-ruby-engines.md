---
title: ERB / Haml SSTI
type: concept
related: [[Server-Side Template Injection]]
---

ERB và Haml cho phép Ruby evaluation trực tiếp, nên command execution thường rất gần.

Backticks, `IO.popen`, `Open3.capture2`, `system`, `instance_eval`, và `class_eval` là các đường dẫn quan trọng.