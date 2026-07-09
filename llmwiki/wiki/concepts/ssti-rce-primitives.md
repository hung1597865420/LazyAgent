---
title: SSTI RCE Primitives
type: concept
related: [[Server-Side Template Injection]]
---

Các primitive RCE theo ngôn ngữ được nhắc đến:

- Python: `os.system`, `os.popen`, `subprocess.run`, `subprocess.Popen`
- Java: `Runtime.getRuntime().exec`, `ProcessBuilder`, `freemarker.template.utility.Execute`
- Ruby: backticks, `system`, `exec`, `Open3.capture2`, `IO.popen`, `%x{}`
- JavaScript/Node: `require('child_process').execSync` / `exec` / `spawn`
- PHP: `system`, `passthru`, `exec`, `shell_exec`, backticks, `popen`